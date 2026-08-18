import httpx
import pytest
import respx
from ocr_service.backend.remote import RemoteOcrBackend
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import HostRef, NoHostAvailableError, StaticHostRegistry
from vypq_core.http_client import UpstreamError

HOST_A = "http://gpu-a:9000"
HOST_B = "http://gpu-b:9000"

OK_BODY = {
    "model_id": "m1",
    "task": "ocr",
    "output": {"boxes": [
        {"id": 0, "polygon": [[0, 0], [10, 0], [10, 5], [0, 5]], "text": "A"}
    ]},
    "timing": {"load_ms": 0, "infer_ms": 7},
}


def _host(name: str, url: str) -> HostRef:
    return HostRef(
        name=name, url=url, token="tk",
        models=[ModelInfo(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")],
    )


async def _noop_sleep(_s: float) -> None:
    return None


def _backend(hosts: list[HostRef], **kw) -> RemoteOcrBackend:
    return RemoteOcrBackend(
        StaticHostRegistry(hosts), sleep=_noop_sleep, jitter=lambda: 0.0, **kw
    )


@respx.mock
async def test_infer_posts_multipart_and_parses_boxes():
    route = respx.post(f"{HOST_A}/v1/infer/upload").mock(
        return_value=httpx.Response(200, json=OK_BODY)
    )
    backend = _backend([_host("a", HOST_A)])
    output = await backend.infer(b"\xff\xd8jpeg", "m1")
    assert output.boxes[0].text == "A"
    assert route.called
    assert b"multipart/form-data" in route.calls[0].request.headers["content-type"].encode()


@respx.mock
async def test_infer_sends_bearer_token_of_the_chosen_host():
    captured: dict[str, str] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=OK_BODY)

    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=_record)
    await _backend([_host("a", HOST_A)]).infer(b"x", "m1")
    assert captured["auth"] == "Bearer tk"


@respx.mock
async def test_infer_uri_posts_json_instead_of_multipart():
    # Đường uri có sẵn cho Plan B (khi máy GPU cùng mạng với MinIO); Plan A dùng inline.
    route = respx.post(f"{HOST_A}/v1/infer").mock(return_value=httpx.Response(200, json=OK_BODY))
    backend = _backend([_host("a", HOST_A)])
    await backend.infer_uri("https://minio/a.jpg", "m1")
    assert route.called
    assert route.calls[0].request.headers["content-type"] == "application/json"


async def test_unknown_model_raises_no_host_available():
    with pytest.raises(NoHostAvailableError):
        await _backend([_host("a", HOST_A)]).infer(b"x", "khong-co")


@respx.mock
async def test_breaker_is_shared_across_calls_to_the_same_host():
    # Nếu mỗi lần gọi lại tạo client mới, breaker sẽ reset và không bao giờ mở.
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    backend = _backend([_host("a", HOST_A)], max_attempts=1, failure_threshold=2)
    for _ in range(2):
        with pytest.raises(UpstreamError):
            await backend.infer(b"x", "m1")
    with pytest.raises(CircuitOpenError):
        await backend.infer(b"x", "m1")


@respx.mock
async def test_each_host_has_its_own_breaker():
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    respx.post(f"{HOST_B}/v1/infer/upload").mock(return_value=httpx.Response(200, json=OK_BODY))
    hosts = [_host("a", HOST_A), _host("b", HOST_B)]
    backend = _backend(hosts, max_attempts=1, failure_threshold=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")
    hosts[0].healthy = False
    output = await backend.infer(b"x", "m1")
    assert output.boxes[0].text == "A"


@respx.mock
async def test_client_is_rebuilt_when_the_host_changes_its_url():
    # Máy thuê lại: cùng tên host, URL ngrok mới. Cache theo tên thôi sẽ gửi
    # request tới tunnel cũ đã chết mãi mãi.
    old = respx.post(f"{HOST_A}/v1/infer/upload").mock(
        return_value=httpx.Response(200, json=OK_BODY)
    )
    new = respx.post(f"{HOST_B}/v1/infer/upload").mock(
        return_value=httpx.Response(200, json=OK_BODY)
    )
    hosts = [_host("gpu-1", HOST_A)]
    backend = _backend(hosts)

    await backend.infer(b"x", "m1")
    assert old.called and not new.called

    hosts[0].url = HOST_B                      # thuê lại, URL mới
    await backend.infer(b"x", "m1")
    assert new.called
    await backend.aclose()


@respx.mock
async def test_inflight_returns_to_zero_after_failure():
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    hosts = [_host("a", HOST_A)]
    backend = _backend(hosts, max_attempts=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")
    assert hosts[0].inflight == 0
