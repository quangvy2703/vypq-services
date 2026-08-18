import asyncio
import random
from collections.abc import Awaitable, Callable

from vypq_contracts.hosting import InferRequest, InferResponse
from vypq_contracts.ocr import RawOcrOutput
from vypq_core.breaker import CircuitBreaker
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
        self._clients: dict[str, UpstreamClient] = {}

    def _client_for(self, host: HostRef) -> UpstreamClient:
        if host.name not in self._clients:
            self._clients[host.name] = UpstreamClient(
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
            )
        return self._clients[host.name]

    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput:
        # pick() rồi mới lease(): giữa hai lời gọi không được có await nào, nếu
        # không nhiều coroutine cùng đọc inflight cũ và dồn hết vào một host.
        host = await self._registry.pick(model_id)
        async with self._registry.lease(host):
            response = await self._client_for(host).request(
                "POST",
                "/v1/infer/upload",
                data={"model_id": model_id},
                files={"file": ("input", image, "application/octet-stream")},
            )
        return self._parse(response.json())

    async def infer_uri(self, uri: str, model_id: str) -> RawOcrOutput:
        host = await self._registry.pick(model_id)
        payload = InferRequest(model_id=model_id, input_uri=uri)
        async with self._registry.lease(host):
            response = await self._client_for(host).request(
                "POST", "/v1/infer", json=payload.model_dump(mode="json")
            )
        return self._parse(response.json())

    @staticmethod
    def _parse(body: dict) -> RawOcrOutput:
        parsed = InferResponse.model_validate(body)
        assert isinstance(parsed.output, RawOcrOutput)
        return parsed.output

    def open_circuits(self) -> list[str]:
        """Tên các host đang bị circuit chặn — dùng cho /ready."""
        return [n for n, c in self._clients.items() if c.breaker.is_open()]

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
