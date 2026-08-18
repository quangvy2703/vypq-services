from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class HostRegistry(Protocol):
    async def hosts(self) -> list[HostRef]: ...
    async def pick(self, model_id: str) -> HostRef: ...
    def models_for_task(self, task: Task) -> list[ModelInfo]: ...
    # lease() phải nằm trong Protocol: Plan B thay bằng bản discovery, thiếu khai
    # báo ở đây thì bản đó quên cài mà type checker không kêu, chỉ vỡ lúc chạy.
    # Lưu ý @runtime_checkable chỉ kiểm method CÓ MẶT, không kiểm chữ ký: một bản
    # cài lease() thành hàm sync vẫn qua được isinstance.
    def lease(self, host: HostRef) -> AbstractAsyncContextManager[HostRef]: ...


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
        """Danh mục model, hiểu đúng theo nghĩa `pick()` dùng.

        `available=True` nghĩa là NGAY LÚC NÀY có host khoẻ phục vụ được — tức là
        `pick()` sẽ thành công. Nếu không, model vẫn được liệt kê nhưng
        `available=False`: bỏ hẳn khỏi danh mục thì không ai biết nó tồn tại, còn
        báo available trong khi `pick()` từ chối thì tệ hơn cả hai, vì caller tin
        danh mục để định tuyến rồi ăn 503.

        Xét cả `host.healthy` chứ không chỉ `model.available`: chỉ nhìn
        `model.available` sẽ báo khoẻ cho model nằm trên một máy thuê đã tắt.
        """
        best: dict[str, tuple[int, ModelInfo]] = {}
        for host in self._hosts:
            for model in host.models:
                if model.task is not task:
                    continue
                servable = host.healthy and model.available
                current = best.get(model.id)
                if current is not None and current[0] >= int(servable):
                    continue
                entry = model if servable else model.model_copy(update={"available": False})
                best[model.id] = (int(servable), entry)
        return [entry for _rank, entry in best.values()]

    @asynccontextmanager
    async def lease(self, host: HostRef):
        host.inflight += 1
        try:
            yield host
        finally:
            host.inflight -= 1
