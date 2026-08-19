import httpx
import pytest
import respx
from gateway.api.invoke import build_invoke_router
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.main import build_app
from gateway.proxy import SyncProxy
from gateway.registry.services import ServiceEntry, ServiceRegistry
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import RunStatus, ServiceInfo, ServiceState

OCR_RESULT = {
    "trace_id": "t1", "model_version": "m1", "latency_ms": 12,
    "result": {"full_text": "xin chào", "boxes": []},
}


def _state(status=HealthStatus.OK) -> ServiceState:
    return ServiceState(
        info=ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0",
            invoke_path="/v1/ocr", default_model="m1",
        ),
        base_url="http://ocr:8001",
        status=status,
    )


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = ServiceRegistry([ServiceEntry(name="ocr", base_url="http://ocr:8001")])
    registry._states["ocr"] = _state()
    proxy = SyncProxy(registry, factory)
    app = build_app(factory, GatewaySettings(service_name="gateway"),
                    routers=[build_invoke_router(proxy)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory, registry
    await registry.aclose()
    await proxy.aclose()
    await engine.dispose()


@respx.mock
async def test_upload_reaches_the_service_and_returns_its_result(ctx):
    client, _factory, _reg = ctx
    route = respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(200, json=OCR_RESULT)
    )
    resp = await client.post(
        "/v1/invoke/upload",
        data={"service": "ocr"},
        files={"file": ("a.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["full_text"] == "xin chào"
    assert route.called


@respx.mock
async def test_every_invocation_is_recorded(ctx):
    client, factory, _reg = ctx
    respx.post("http://ocr:8001/v1/ocr").mock(return_value=httpx.Response(200, json=OCR_RESULT))
    await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.OK
    assert runs[0].service == "ocr"
    assert runs[0].latency_ms is not None


@respx.mock
async def test_service_failure_is_recorded_as_failed_not_dropped(ctx):
    # Lỗi vẫn phải vào lịch sử — đó là lúc người ta cần lịch sử nhất.
    client, factory, _reg = ctx
    respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(503, json={"code": "upstream_error", "message": "gpu chết"})
    )
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code >= 400
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].error


async def test_unknown_service_is_404(ctx):
    client, _factory, _reg = ctx
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "khong-co"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 404


@respx.mock
async def test_down_service_is_refused_before_sending_anything(ctx):
    # Không gửi request vào một service đã biết là chết: 503 ngay, rõ lý do,
    # và không được đụng tới downstream lẫn lịch sử runs.
    client, factory, registry = ctx
    route = respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(200, json=OCR_RESULT)
    )
    registry._states["ocr"] = _state(HealthStatus.DOWN)
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 503
    assert not route.called
    async with factory() as s:
        _runs, total = await RunRepo(s).list_runs()
    assert total == 0


async def test_service_with_no_info_is_refused_without_recording(ctx):
    # Chưa poll được lần nào nên chưa biết invoke_path: từ chối ngay, không
    # ghi dòng nào — nửa còn lại của ranh giới ghi runs, trước đây chưa có test.
    client, factory, registry = ctx
    registry._states["ocr"] = ServiceState(
        info=None, base_url="http://ocr:8001", status=HealthStatus.OK
    )
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 503
    async with factory() as s:
        _runs, total = await RunRepo(s).list_runs()
    assert total == 0


@respx.mock
async def test_caller_trace_id_agrees_everywhere(ctx):
    # Bug gốc: header response, body, dòng runs và header gửi xuống service có
    # thể mang bốn giá trị khác nhau. Giờ tất cả phải khớp với trace_id caller
    # gửi lên, chứ không phải một UUID mới sinh ra ở đâu đó giữa đường.
    client, factory, _reg = ctx
    downstream_headers = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        downstream_headers["x-trace-id"] = request.headers.get("x-trace-id")
        return httpx.Response(200, json=OCR_RESULT)

    respx.post("http://ocr:8001/v1/ocr").mock(side_effect=_capture)
    resp = await client.post(
        "/v1/invoke/upload",
        data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
        headers={"x-trace-id": "caller-supplied-trace-abc"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-trace-id"] == "caller-supplied-trace-abc"
    assert resp.json()["trace_id"] == "caller-supplied-trace-abc"
    assert downstream_headers["x-trace-id"] == "caller-supplied-trace-abc"
    async with factory() as s:
        runs, _total = await RunRepo(s).list_runs()
    assert runs[0].trace_id == "caller-supplied-trace-abc"


@respx.mock
async def test_no_inbound_trace_id_still_generates_a_consistent_one(ctx):
    # Không có header thì vẫn phải sinh trace_id mới như cũ — nhưng body và
    # dòng runs phải khớp nhau (đều lấy từ cùng một giá trị được sinh ra).
    client, factory, _reg = ctx
    respx.post("http://ocr:8001/v1/ocr").mock(return_value=httpx.Response(200, json=OCR_RESULT))
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 200
    body_trace_id = resp.json()["trace_id"]
    assert body_trace_id
    async with factory() as s:
        runs, _total = await RunRepo(s).list_runs()
    assert runs[0].trace_id == body_trace_id


@respx.mock
async def test_model_version_is_forwarded_to_the_service(ctx):
    client, _factory, _reg = ctx
    captured = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json=OCR_RESULT)

    respx.post("http://ocr:8001/v1/ocr").mock(side_effect=_record)
    await client.post(
        "/v1/invoke/upload",
        data={"service": "ocr", "model_version": "vietocr-ft"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert b"vietocr-ft" in captured["body"]


@respx.mock
async def test_input_uri_is_fetched_then_forwarded_as_multipart(ctx):
    # Service chỉ có một đường vào là multipart; tự tải URI là việc của worker.
    client, _factory, _reg = ctx
    respx.get("http://minio/a.png").mock(return_value=httpx.Response(200, content=b"\x89PNG"))
    route = respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(200, json=OCR_RESULT)
    )
    resp = await client.post(
        "/v1/invoke", json={"service": "ocr", "input_uri": "http://minio/a.png"}
    )
    assert resp.status_code == 200
    assert route.called
