import httpx
import respx
from gateway.registry.services import ServiceEntry, ServiceRegistry
from vypq_contracts.common import HealthStatus, Task

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
    assert reg.get("ocr") is not None       # vẫn liệt kê để biết nó tồn tại
    assert state.info is None               # nhưng chưa từng nói chuyện được: không đoán
    await reg.aclose()


def test_never_polled_service_has_no_info():
    # Chưa refresh lần nào (hoặc chưa lần nào thành công) thì info PHẢI là
    # None. Đây chính là hố định tuyến: nếu info bị đoán ra (như bug cũ luôn
    # hardcode Task.OCR), một dispatcher async không kiểm status trước khi
    # publish sẽ đẩy nhầm request của service này (vd "asr") sang topic Kafka
    # của Task.OCR — âm thầm, sau khi caller đã nhận trace_id và tin là việc
    # đã được nhận.
    reg = _registry(ServiceEntry(name="asr", base_url="http://asr:8003"))
    state = reg.get("asr")
    assert state.info is None


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
    # Một lần refresh trượt không được xoá mất hiểu biết về service. Đây là
    # ranh giới với info=None: đã từng thành công thì giữ ServiceInfo THẬT,
    # chỉ chưa từng thành công mới mang None. Ranh giới này phải được ghim lại
    # để một lần đơn giản hoá sau này không gộp nhầm hai trường hợp làm một.
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
    assert state.info is not None
    assert state.info.task is Task.OCR
    assert state.info.invoke_path == "/v1/ocr"   # vẫn nhớ đường gọi
    await reg.aclose()


@respx.mock
async def test_parse_failure_in_one_service_does_not_stop_another():
    # Lỗi xảy ra ở BƯỚC PARSE (ServiceInfo.model_validate), không phải lỗi
    # HTTP — response 200 nhưng thân JSON thiếu field bắt buộc. Đường này
    # không được các test cô lập khác chạm tới, và chính là đường mà state
    # assignment nằm ngoài try/except nếu bị sửa bất cẩn trong tương lai.
    respx.get("http://a:8001/v1/info").mock(
        return_value=httpx.Response(200, json={"thieu": "cac field bat buoc"})
    )
    respx.get("http://b:8002/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://b:8002/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(
        ServiceEntry(name="a", base_url="http://a:8001"),
        ServiceEntry(name="b", base_url="http://b:8002"),
    )
    await reg.refresh()
    assert reg.get("a").status is HealthStatus.DOWN
    assert reg.get("a").info is None
    assert reg.get("b").status is HealthStatus.OK
    assert reg.get("b").info.invoke_path == "/v1/ocr"
    await reg.aclose()


def test_get_unknown_service_returns_none():
    assert _registry().get("khong-co") is None
