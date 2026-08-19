import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field
from vypq_contracts.common import ErrorCode, Task
from vypq_contracts.hosting import ModelInfo

from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)


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
    async def aclose(self) -> None: ...


def _pick_from(hosts: list[HostRef], model_id: str) -> HostRef:
    candidates = [h for h in hosts if h.healthy and h.has_model(model_id)]
    if not candidates:
        raise NoHostAvailableError(model_id)
    return min(candidates, key=lambda h: h.inflight)


def _models_for_task_from(hosts: list[HostRef], task: Task) -> list[ModelInfo]:
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
    for host in hosts:
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
async def _lease(host: HostRef):
    host.inflight += 1
    try:
        yield host
    finally:
        host.inflight -= 1


class StaticHostRegistry:
    """Danh sách host cố định từ config. Plan B thay bằng DiscoveryHostRegistry."""

    def __init__(self, hosts: list[HostRef]) -> None:
        self._hosts = hosts

    async def hosts(self) -> list[HostRef]:
        return list(self._hosts)

    async def pick(self, model_id: str) -> HostRef:
        return _pick_from(self._hosts, model_id)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        return _models_for_task_from(self._hosts, task)

    # BỎ decorator @asynccontextmanager ở đây: nó đã nằm trên `_lease`. Để cả
    # hai chỗ sẽ bọc hai lớp và `async with` nhận về context manager thay vì host.
    def lease(self, host: HostRef):
        return _lease(host)

    # Không có client nào để đóng, nhưng vẫn cần tồn tại: caller đóng registry
    # mà không cần biết đang cầm bản static hay discovery.
    async def aclose(self) -> None:
        return None


class DiscoveryResponse(BaseModel):
    """Thân trả lời của gateway cho service hỏi danh sách host.

    Dùng `HostRef` nguyên vẹn — CÓ token — vì service cần token để gọi
    model-host. Endpoint này chỉ được phơi trong mạng nội bộ, khác với
    `GET /v1/hosts` dành cho dashboard và không mang token.
    """

    hosts: list[HostRef] = Field(default_factory=list)


class DiscoveryHostRegistry:
    """Lấy danh sách host từ gateway, làm mới định kỳ.

    Cùng Protocol với StaticHostRegistry nên service không phải sửa gì ngoài
    một dòng config.
    """

    def __init__(
        self,
        url: str,
        *,
        refresh_s: float = 15.0,
        fallback: list[HostRef] | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._refresh_s = refresh_s
        self._clock = clock
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._cached: list[HostRef] = list(fallback or [])
        self._fetched_at: float | None = None

    async def hosts(self) -> list[HostRef]:
        now = self._clock()
        if self._fetched_at is not None and now - self._fetched_at < self._refresh_s:
            return self._cached
        try:
            response = await self._client.get(self._url)
            response.raise_for_status()
            fresh = DiscoveryResponse.model_validate(response.json()).hosts
            # `GET /v1/hosts` (dashboard, không token) parse THÀNH CÔNG vào cùng
            # kiểu này vì `token` mặc định None — nhầm URL đó thay vì
            # `/v1/discovery/hosts` không lộ ra lỗi nào ở đây, chỉ lộ ra sau
            # hàng giờ khi mọi lệnh gọi model-host đều 401. Không ném lỗi vì một
            # deployment có thể cố ý chạy model-host không cần token — chỉ cảnh
            # báo để operator để ý ngay, thay vì tự suy luận từ log 401.
            if fresh and all(h.token is None for h in fresh):
                log.warning(
                    "host_discovery_tokens_missing",
                    url=self._url,
                    hint="url có thể đang trỏ vào danh sách không token (dashboard)"
                    " thay vì /v1/discovery/hosts",
                )
        except Exception as exc:
            # Gateway sập không được kéo theo mọi service: danh sách cũ vẫn tốt
            # hơn danh sách rỗng, vì host trong đó có thể vẫn đang chạy.
            log.warning("host_discovery_failed", url=self._url, error=str(exc))
            self._fetched_at = now
            return self._cached

        # inflight sống ở đối tượng HostRef, và lease() giữ tham chiếu THẲNG tới
        # đối tượng đó (xem `_lease` dùng chung ở Step 3). Nếu refresh luôn dựng
        # HostRef hoàn toàn mới, một lease đang mở lúc refresh xảy ra sẽ giảm
        # inflight trên đối tượng CŨ trong khi cache đã trỏ sang đối tượng MỚI —
        # số đếm kẹt lại, không bao giờ về 0. Vì vậy: với host đã tồn tại, giữ
        # nguyên định danh đối tượng (cập nhật field tại chỗ, trừ inflight) thay
        # vì thay bằng đối tượng khác; chỉ host thật sự mới mới được tạo mới.
        existing = {h.name: h for h in self._cached}
        merged: list[HostRef] = []
        for host in fresh:
            prior = existing.get(host.name)
            if prior is None:
                merged.append(host)
                continue
            for field_name in HostRef.model_fields:
                if field_name == "inflight":
                    continue
                setattr(prior, field_name, getattr(host, field_name))
            merged.append(prior)
        self._cached = merged
        self._fetched_at = now
        return self._cached

    async def pick(self, model_id: str) -> HostRef:
        return _pick_from(await self.hosts(), model_id)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        return _models_for_task_from(self._cached, task)

    def lease(self, host: HostRef):
        return _lease(host)

    async def aclose(self) -> None:
        await self._client.aclose()
