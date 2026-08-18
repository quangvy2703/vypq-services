import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx
from vypq_contracts.common import ErrorCode

from vypq_core.breaker import CircuitBreaker, CircuitOpenError
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)


class UpstreamError(ServiceError):
    """Lỗi tạm thời phía upstream — đáng retry và làm sập circuit."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.UPSTREAM_ERROR) -> None:
        super().__init__(code, message, http_status=503)


class UpstreamClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        base_delay_s: float = 0.2,
        breaker: CircuitBreaker | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.breaker = breaker or CircuitBreaker()
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._sleep = sleep
        self._jitter = jitter
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout_s, headers=headers
        )

    async def __aenter__(self) -> "UpstreamClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.breaker.allow():
            raise CircuitOpenError(self.base_url)

        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                code = (
                    ErrorCode.UPSTREAM_TIMEOUT
                    if isinstance(exc, httpx.TimeoutException)
                    else ErrorCode.UPSTREAM_ERROR
                )
                last = UpstreamError(f"{self.base_url}: {exc}", code)
            else:
                if response.status_code < 400:
                    self.breaker.record_success()
                    return response
                if response.status_code < 500:
                    # 4xx là lỗi của request, thử lại vẫn sai → không retry.
                    # Nhưng host RỔI SỐNG mới trả được 4xx, nên phải record_success:
                    # thoát ra mà không báo gì sẽ để probe half-open treo vĩnh viễn.
                    self.breaker.record_success()
                    raise ServiceError(
                        ErrorCode.BAD_INPUT,
                        f"upstream từ chối ({response.status_code}): {response.text[:200]}",
                        http_status=response.status_code,
                    )
                last = UpstreamError(f"{self.base_url} trả {response.status_code}")

            if attempt < self._max_attempts:
                delay = self._base_delay * (2 ** (attempt - 1))
                await self._sleep(delay + self._jitter() * delay * 0.1)
                log.warning("upstream_retry", url=self.base_url, attempt=attempt)

        self.breaker.record_failure()
        assert last is not None
        raise last
