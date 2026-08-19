import httpx
import respx
from gateway.registry.services import ServiceEntry, ServiceRegistry
from vypq_contracts.common import HealthStatus

INFO_BODY = {
    "name": "ocr", "task": "ocr", "capability_input": "image",
    "capability_output": "text_boxes", "version": "0.1.0",
    "invoke_path": "/v1/ocr", "default_model": "m1",
}


def _registry(*entries: ServiceEntry) -> ServiceRegistry:
    return ServiceRegistry(list(entries))


@respx.mock
async def test_refresh_reads_info_and_health():
    respx.get("http://ocr:8001/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.OK
    assert state.info.invoke_path == "/v1/ocr"
    await reg.aclose()


@respx.mock
async def test_degraded_ready_is_reported_not_hidden():
    # /ready trả 503 nghĩa là service còn sống nhưng upstream của nó có vấn đề.
    # Giấu đi thì dashboard báo xanh trong khi request đang hỏng.
    respx.get("http://ocr:8001/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(503, json={
        "status": "degraded", "service": "ocr", "version": "0.1.0",
        "detail": {"model_host": "circuit đang mở"}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    assert reg.get("ocr").status is HealthStatus.DEGRADED
    await reg.aclose()


@respx.mock
async def test_unreachable_service_is_down_but_still_listed():
    respx.get("http://ocr:8001/v1/info").mock(side_effect=httpx.ConnectError("chết"))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.DOWN
    assert state.info.name == "ocr"        # vẫn liệt kê để biết nó tồn tại
    await reg.aclose()


@respx.mock
async def test_one_dead_service_does_not_stop_the_others():
    respx.get("http://a:8001/v1/info").mock(side_effect=httpx.ConnectError("chết"))
    respx.get("http://b:8002/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://b:8002/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(
        ServiceEntry(name="a", base_url="http://a:8001"),
        ServiceEntry(name="b", base_url="http://b:8002"),
    )
    await reg.refresh()
    assert reg.get("a").status is HealthStatus.DOWN
    assert reg.get("b").status is HealthStatus.OK
    await reg.aclose()


@respx.mock
async def test_previous_info_is_kept_when_a_refresh_fails():
    # Một lần refresh trượt không được xoá mất hiểu biết về service.
    respx.get("http://ocr:8001/v1/info").mock(
        side_effect=[httpx.Response(200, json=INFO_BODY), httpx.ConnectError("chết")]
    )
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.DOWN
    assert state.info.invoke_path == "/v1/ocr"   # vẫn nhớ đường gọi
    await reg.aclose()


def test_get_unknown_service_returns_none():
    assert _registry().get("khong-co") is None
