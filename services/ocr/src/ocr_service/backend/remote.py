import asyncio
import random
from collections.abc import Awaitable, Callable

from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import InferRequest, InferResponse
from vypq_contracts.ocr import RawOcrOutput
from vypq_core.breaker import CircuitBreaker
from vypq_core.errors import ServiceError
from vypq_core.host_registry import HostRef, StaticHostRegistry
from vypq_core.http_client import UpstreamClient


class RemoteOcrBackend:
    """Gọi model-host qua HTTP. Giữ một UpstreamClient cho mỗi host để circuit
    breaker sống xuyên suốt các lần gọi — tạo client mới mỗi lần sẽ reset breaker
    và nó không bao giờ mở được."""

    def __init__(
        self,
        registry: StaticHostRegistry,
        *,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._registry = registry
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._sleep = sleep
        self._jitter = jitter
        # tên host -> ((url, token), client). Xem _client_for để biết vì sao khoá kép.
        self._clients: dict[str, tuple[tuple[str, str | None], UpstreamClient]] = {}

    async def _client_for(self, host: HostRef) -> UpstreamClient:
        # Khoá cache theo (url, token) chứ không chỉ theo tên: máy GPU thuê lại
        # giữ nguyên tên nhưng ĐỔI URL ngrok mỗi lần thuê. Nhớ theo tên thôi là
        # ghim service vào tunnel đã chết, không có đường tự khỏi ngoài restart.
        key = (host.url, host.token)
        cached = self._clients.get(host.name)
        if cached is not None and cached[0] != key:
            await cached[1].aclose()
            cached = None
        if cached is None:
            cached = (
                key,
                UpstreamClient(
                    host.url,
                    token=host.token,
                    timeout_s=self._timeout_s,
                    max_attempts=self._max_attempts,
                    breaker=CircuitBreaker(
                        failure_threshold=self._failure_threshold,
                        recovery_timeout_s=self._recovery_timeout_s,
                    ),
                    sleep=self._sleep,
                    jitter=self._jitter,
                ),
            )
            self._clients[host.name] = cached
        return cached[1]

    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput:
        # pick() rồi mới lease(): giữa hai lời gọi không được có await nào, nếu
        # không nhiều coroutine cùng đọc inflight cũ và dồn hết vào một host.
        host = await self._registry.pick(model_id)
        client = await self._client_for(host)
        async with self._registry.lease(host):
            response = await client.request(
                "POST",
                "/v1/infer/upload",
                data={"model_id": model_id},
                files={"file": ("input", image, "application/octet-stream")},
            )
        return self._parse(response.json())

    async def infer_uri(self, uri: str, model_id: str) -> RawOcrOutput:
        host = await self._registry.pick(model_id)
        client = await self._client_for(host)
        payload = InferRequest(model_id=model_id, input_uri=uri)
        async with self._registry.lease(host):
            response = await client.request(
                "POST", "/v1/infer", json=payload.model_dump(mode="json")
            )
        return self._parse(response.json())

    @staticmethod
    def _parse(body: dict) -> RawOcrOutput:
        parsed = InferResponse.model_validate(body)
        if not isinstance(parsed.output, RawOcrOutput):
            # assert sẽ bị python -O gỡ bỏ; đây là dữ liệu từ máy khác nên phải
            # kiểm thật và báo lỗi rõ thay vì AssertionError rơi vào handler 500.
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"model-host trả output kiểu {type(parsed.output).__name__} cho task ocr",
                http_status=502,
            )
        return parsed.output

    def open_circuits(self) -> list[str]:
        """Tên các host đang bị circuit chặn — dùng cho /ready."""
        return [n for n, (_key, c) in self._clients.items() if c.breaker.is_open()]

    async def aclose(self) -> None:
        for _key, client in self._clients.values():
            await client.aclose()
        self._clients.clear()
