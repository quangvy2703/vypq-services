from contextlib import asynccontextmanager
from typing import Protocol

from pydantic import BaseModel, Field
from vypq_contracts.common import ErrorCode, Task
from vypq_contracts.hosting import ModelInfo

from vypq_core.errors import ServiceError


class NoHostAvailableError(ServiceError):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            ErrorCode.MODEL_UNAVAILABLE,
            f"không có host khoẻ nào phục vụ model '{model_id}'",
            http_status=503,
        )


class HostRef(BaseModel):
    name: str
    url: str
    token: str | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    healthy: bool = True
    inflight: int = 0

    def has_model(self, model_id: str) -> bool:
        return any(m.id == model_id and m.available for m in self.models)


class HostRegistry(Protocol):
    async def hosts(self) -> list[HostRef]: ...
    async def pick(self, model_id: str) -> HostRef: ...
    def models_for_task(self, task: Task) -> list[ModelInfo]: ...


class StaticHostRegistry:
    """Danh sách host cố định từ config. Plan B thay bằng DiscoveryHostRegistry."""

    def __init__(self, hosts: list[HostRef]) -> None:
        self._hosts = hosts

    async def hosts(self) -> list[HostRef]:
        return list(self._hosts)

    async def pick(self, model_id: str) -> HostRef:
        candidates = [h for h in self._hosts if h.healthy and h.has_model(model_id)]
        if not candidates:
            raise NoHostAvailableError(model_id)
        return min(candidates, key=lambda h: h.inflight)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        seen: dict[str, ModelInfo] = {}
        for host in self._hosts:
            for model in host.models:
                if model.task is task and model.id not in seen:
                    seen[model.id] = model
        return list(seen.values())

    @asynccontextmanager
    async def lease(self, host: HostRef):
        host.inflight += 1
        try:
            yield host
        finally:
            host.inflight -= 1
