import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field
from vypq_contracts.common import HealthStatus
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
    # info=None: gateway chưa nói chuyện được với service này lần nào, nên
    # không có gì để đoán task hay invoke_path. Đoán từng là bug: hardcode
    # Task.OCR khiến một service khác OCR chưa poll được có thể bị định
    # tuyến/publish nhầm sang topic của OCR.
    return ServiceState(
        name=entry.name, info=None, base_url=entry.base_url, status=HealthStatus.DOWN
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
        # return_exceptions=True là bảo đảm CẤU TRÚC, giống HostPoller: một
        # _refresh_one hỏng ở đâu đó ngoài dự tính cũng chỉ hạ đúng service
        # đó, không giết cả gather và làm registry đứng im, âm thầm.
        results = await asyncio.gather(
            *(self._refresh_one(e) for e in self._entries),
            return_exceptions=True,
        )
        for entry, result in zip(self._entries, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                # Huỷ là tín hiệu tắt máy, không phải lỗi của service — phải
                # bay tiếp, nếu không lifespan sẽ treo khi shutdown.
                raise result
            if isinstance(result, BaseException):
                log.exception("service_refresh_crashed", service=entry.name, error=str(result))

    async def _refresh_one(self, entry: ServiceEntry) -> None:
        """Poll một service và cập nhật trạng thái của nó.

        Lưu ý: `last_seen_at` được set ngay khi GET /v1/info thành công, kể cả
        khi bước /ready ngay sau đó thất bại. Vậy nó có nghĩa là "lần cuối
        GATEWAY CHẠM ĐƯỢC service" (last reached), KHÔNG phải "lần cuối service
        khoẻ" (last healthy) — status mới là trường mang tình trạng khoẻ mạnh.
        """
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

        if info.name != entry.name:
            # Không tự sửa: gateway vẫn định tuyến bằng khoá yaml, và đổi sang
            # tên service tự khai sẽ làm hỏng mọi đường đang chạy. Chỉ nói ra,
            # vì lệch hai tên này trước đây hỏng hoàn toàn im lặng.
            log.warning(
                "service_name_mismatch", service=entry.name, declared=info.name,
                detail="tên trong services.yaml khác tên service tự khai qua /v1/info",
            )
        self._states[entry.name] = ServiceState(
            name=entry.name, info=info, base_url=entry.base_url, status=status,
            last_seen_at=datetime.now(UTC),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
