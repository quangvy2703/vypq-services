import asyncio

import httpx
import pytest
import respx
from vypq_core.breaker import CircuitBreaker, CircuitOpenError, CircuitState
from vypq_core.errors import ServiceError
from vypq_core.http_client import UpstreamClient, UpstreamError

BASE = "http://gpu-box:9001"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _noop_sleep(_seconds: float) -> None:
    return None


def _client(**kw) -> UpstreamClient:
    kw.setdefault("sleep", _noop_sleep)
    kw.setdefault("jitter", lambda: 0.0)
    return UpstreamClient(BASE, **kw)


@respx.mock
async def test_returns_response_on_success():
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with _client() as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.json() == {"ok": True}


@respx.mock
async def test_retries_on_500_then_succeeds():
    route = respx.get(f"{BASE}/v1/models").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    async with _client(max_attempts=3) as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_does_not_retry_on_400():
    route = respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(400, text="sai"))
    async with _client(max_attempts=3) as c:
        with pytest.raises(ServiceError) as exc:
            await c.request("GET", "/v1/models")
    assert route.call_count == 1
    assert exc.value.http_status == 400
    assert not isinstance(exc.value, UpstreamError)


@respx.mock
async def test_retries_on_connect_error_then_raises_upstream_error():
    route = respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    async with _client(max_attempts=3) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert route.call_count == 3


@respx.mock
async def test_timeout_is_reported_as_upstream_error():
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ReadTimeout("quá hạn"))
    async with _client(max_attempts=1) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")


@respx.mock
async def test_breaker_opens_after_repeated_failures_and_short_circuits():
    route = respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        for _ in range(2):
            with pytest.raises(UpstreamError):
                await c.request("GET", "/v1/models")
        assert breaker.state is CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await c.request("GET", "/v1/models")
    # Lần thứ ba bị chặn tại chỗ, không gửi request nào ra ngoài.
    assert route.call_count == 2


@respx.mock
async def test_4xx_does_not_trip_the_breaker():
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(422))
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        for _ in range(3):
            with pytest.raises(ServiceError):
                await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.CLOSED


@respx.mock
async def test_bad_input_4xx_during_half_open_probe_closes_the_circuit():
    # Host trả 4xx dữ liệu hỏng nghĩa là host còn sống. Nếu đường này thoát ra
    # mà không báo gì cho breaker, probe treo lại và circuit kẹt vĩnh viễn.
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("chết"))
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0, clock=clock)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
        assert breaker.state is CircuitState.OPEN

        respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(422))
        clock.advance(31.0)
        with pytest.raises(ServiceError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.CLOSED


@respx.mock
async def test_429_is_retried_like_a_5xx():
    route = respx.get(f"{BASE}/v1/models").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    async with _client(max_attempts=3) as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_cancelled_request_still_reports_to_the_breaker():
    # Không báo lại thì probe half-open treo và mất hai chu kỳ recovery.
    def _cancel(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    respx.get(f"{BASE}/v1/models").mock(side_effect=_cancel)
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(asyncio.CancelledError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.OPEN


class _CountingBreaker(CircuitBreaker):
    """Đếm số lần báo để bắt regression double-report."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def record_success(self) -> None:
        self.calls.append("success")
        super().record_success()

    def record_failure(self) -> None:
        self.calls.append("failure")
        super().record_failure()


@respx.mock
async def test_exactly_one_breaker_report_on_every_exit_path():
    respx.get(f"{BASE}/ok").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/bad").mock(return_value=httpx.Response(422))
    respx.get(f"{BASE}/redir").mock(return_value=httpx.Response(302, headers={"location": "/z"}))
    respx.get(f"{BASE}/down").mock(side_effect=httpx.ConnectError("x"))

    cases = [("/ok", None), ("/bad", ServiceError), ("/redir", UpstreamError),
             ("/down", UpstreamError)]
    for path, expected in cases:
        breaker = _CountingBreaker(failure_threshold=99, recovery_timeout_s=30.0)
        async with _client(max_attempts=1, breaker=breaker) as c:
            if expected is None:
                await c.request("GET", path)
            else:
                with pytest.raises(expected):
                    await c.request("GET", path)
        assert len(breaker.calls) == 1, f"{path} báo {breaker.calls}"


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 404, 405, 302])
async def test_infrastructure_statuses_pause_instead_of_dead_lettering(status):
    # Máy thuê lại đổi token -> 401. Tunnel ngrok chết -> 404 từ edge ngrok.
    # Đây là hạ tầng, không phải dữ liệu hỏng: phải là UpstreamError để consumer
    # dừng chờ, và phải mở circuit để /ready báo degraded.
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(status, headers={"location": "https://x/y"})
    )
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.OPEN


@respx.mock
@pytest.mark.parametrize("status", [400, 413, 422])
async def test_bad_input_statuses_stay_permanent(status):
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(status))
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(ServiceError) as exc:
            await c.request("GET", "/v1/models")
    assert not isinstance(exc.value, UpstreamError)
    assert breaker.state is CircuitState.CLOSED      # host vẫn sống


@respx.mock
async def test_bearer_token_is_sent():
    captured: dict[str, str] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    respx.get(f"{BASE}/v1/models").mock(side_effect=_record)
    async with _client(token="sekret") as c:
        await c.request("GET", "/v1/models")
    assert captured["auth"] == "Bearer sekret"


@respx.mock
async def test_backoff_delays_grow_exponentially():
    delays: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        delays.append(seconds)

    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    c = UpstreamClient(
        BASE, max_attempts=4, base_delay_s=0.5, sleep=_record_sleep, jitter=lambda: 0.0
    )
    async with c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert delays == [0.5, 1.0, 2.0]
