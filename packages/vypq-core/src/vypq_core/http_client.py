import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx
from vypq_contracts.common import ErrorCode

from vypq_core.breaker import CircuitBreaker, CircuitOpenError
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)

# 408 và 429 là 4xx nhưng nói về tình trạng upstream chứ không phải lỗi của request:
# hết giờ và quá tải đều đáng thử lại có backoff, giống 5xx.
_RETRYABLE_STATUS = frozenset({408, 429})


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

        reported = False
        try:
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
                    if 300 <= response.status_code < 400:
                        # httpx không tự đi theo redirect. Hay gặp khi base_url để
                        # http:// mà ngrok chuyển sang https:// — coi là thành công
                        # thì downstream nhận body rỗng và vỡ ở chỗ khó lần ra.
                        reported = True
                        self.breaker.record_success()
                        raise ServiceError(
                            ErrorCode.BAD_INPUT,
                            f"upstream trả redirect {response.status_code} tới "
                            f"{response.headers.get('location', '?')} — kiểm tra base_url",
                            http_status=502,
                        )
                    if response.status_code < 400:
                        reported = True
                        self.breaker.record_success()
                        return response
                    if response.status_code >= 500 or response.status_code in _RETRYABLE_STATUS:
                        last = UpstreamError(f"{self.base_url} trả {response.status_code}")
                    else:
                        # 4xx còn lại là lỗi của request, thử lại vẫn sai → không retry.
                        # Nhưng host phải còn sống mới trả được 4xx, nên record_success:
                        # thoát ra mà không báo gì sẽ để probe half-open treo.
                        reported = True
                        self.breaker.record_success()
                        raise ServiceError(
                            ErrorCode.BAD_INPUT,
                            f"upstream từ chối ({response.status_code}): {response.text[:200]}",
                            http_status=response.status_code,
                        )

                if attempt < self._max_attempts:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    await self._sleep(delay + self._jitter() * delay * 0.1)
                    log.warning("upstream_retry", url=self.base_url, attempt=attempt)

            reported = True
            self.breaker.record_failure()
            if last is None:  # pragma: no cover - chỉ xảy ra nếu max_attempts < 1
                raise ValueError(f"max_attempts phải >= 1, đang là {self._max_attempts}")
            raise last
        finally:
            if not reported:
                # `reported` được bật TRƯỚC khi gọi breaker, nên nếu lời gọi đó
                # có ném thì ta bỏ sót một lần báo — thà vậy còn hơn báo hai lần.
                # Lối thoát bất thường: CancelledError khi caller huỷ, lỗi lập trình,
                # KeyboardInterrupt. Không báo lại thì probe half-open bị bỏ treo và
                # phải mất hai chu kỳ recovery mới phục vụ lại được.
                self.breaker.record_failure()
