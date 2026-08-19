import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import ServiceInfo, ServiceState
from vypq_core.logging import get_logger

log = get_logger(__name__)


class ServiceEntry(BaseModel):
    name: str
    base_url: str


class ServicesFile(BaseModel):
    services: list[ServiceEntry] = Field(default_factory=list)


def load_services(path: Path) -> list[ServiceEntry]:
    if not path.is_file():
        return []
    return ServicesFile.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    ).services


def _placeholder(entry: ServiceEntry) -> ServiceState:
    return ServiceState(
        info=ServiceInfo(
            name=entry.name, task=Task.OCR, capability_input="unknown",
            capability_output="unknown", version="unknown", invoke_path="/v1/unknown",
        ),
        base_url=entry.base_url,
        status=HealthStatus.DOWN,
    )


class ServiceRegistry:
    """Biết những service nào tồn tại, chúng làm được gì, và có sống không."""

    def __init__(self, entries: list[ServiceEntry], poll_timeout_s: float = 10.0) -> None:
        self._entries = entries
        self._timeout = poll_timeout_s
        self._states: dict[str, ServiceState] = {e.name: _placeholder(e) for e in entries}
        self._client = httpx.AsyncClient(timeout=poll_timeout_s)

    def states(self) -> list[ServiceState]:
        return [self._states[e.name] for e in self._entries]

    def get(self, name: str) -> ServiceState | None:
        return self._states.get(name)

    async def refresh(self) -> None:
        await asyncio.gather(*(self._refresh_one(e) for e in self._entries))

    async def _refresh_one(self, entry: ServiceEntry) -> None:
        base = entry.base_url.rstrip("/")
        previous = self._states[entry.name]
        try:
            info_resp = await self._client.get(f"{base}/v1/info")
            info_resp.raise_for_status()
            info = ServiceInfo.model_validate(info_resp.json())
        except Exception as exc:
            # Giữ lại hiểu biết cũ: một lần refresh trượt không được xoá mất
            # đường gọi đã biết, nếu không request kế tiếp không biết POST đi đâu.
            log.warning("service_info_failed", service=entry.name, error=str(exc))
            self._states[entry.name] = previous.model_copy(
                update={"status": HealthStatus.DOWN}
            )
            return

        status = HealthStatus.DOWN
        try:
            ready = await self._client.get(f"{base}/ready")
            status = HealthStatus(ready.json().get("status", HealthStatus.DOWN))
        except Exception as exc:
            log.warning("service_ready_failed", service=entry.name, error=str(exc))

        self._states[entry.name] = ServiceState(
            info=info, base_url=entry.base_url, status=status,
            last_seen_at=datetime.now(UTC),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
