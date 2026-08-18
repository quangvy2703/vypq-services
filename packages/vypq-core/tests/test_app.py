import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel
from vypq_contracts.common import ErrorCode, HealthStatus
from vypq_core.app import create_app
from vypq_core.config import BaseServiceSettings
from vypq_core.errors import ServiceError
from vypq_core.logging import get_trace_id, set_trace_id

SETTINGS = BaseServiceSettings(service_name="demo", version="9.9.9")


def _client(app, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    # raise_app_exceptions=False cần cho test handler `Exception`: Starlette gửi
    # response xong vẫn raise lại exception gốc lên ASGI, và ASGITransport mặc
    # định ném nó cho caller. Production dưới uvicorn không có vấn đề này.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://t",
    )


async def test_health_is_ok_even_when_dependencies_are_down():
    async def failing():
        return HealthStatus.DOWN, "upstream chết"

    app = create_app(SETTINGS, readiness={"upstream": failing})
    async with _client(app) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_reports_degraded_when_a_check_is_down():
    async def failing():
        return HealthStatus.DOWN, "upstream chết"

    app = create_app(SETTINGS, readiness={"upstream": failing})
    async with _client(app) as c:
        resp = await c.get("/ready")
    body = resp.json()
    assert resp.status_code == 503
    assert body["status"] == "degraded"
    assert body["detail"]["upstream"] == "upstream chết"


async def test_ready_is_ok_when_all_checks_pass():
    async def fine():
        return HealthStatus.OK, "sẵn sàng"

    app = create_app(SETTINGS, readiness={"upstream": fine})
    async with _client(app) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_service_error_becomes_error_envelope_without_traceback():
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise ServiceError(ErrorCode.BAD_INPUT, "ảnh hỏng", http_status=422)

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/boom")
    body = resp.json()
    assert resp.status_code == 422
    assert body["code"] == "bad_input"
    assert body["message"] == "ảnh hỏng"
    # Middleware luôn gán trace_id, kể cả khi client không gửi — nếu không thì log
    # của mọi request bình thường mất khả năng tương quan.
    assert len(body["trace_id"]) == 32
    assert resp.headers["x-trace-id"] == body["trace_id"]


async def test_unexpected_exception_is_masked_as_internal():
    router = APIRouter()

    @router.get("/crash")
    async def crash():
        raise RuntimeError("chi tiết nội bộ không được lộ ra")

    app = create_app(SETTINGS, routers=[router])
    async with _client(app, raise_app_exceptions=False) as c:
        resp = await c.get("/crash")
    body = resp.json()
    assert resp.status_code == 500
    assert body["code"] == "internal"
    assert "chi tiết nội bộ" not in body["message"]


class _Registration(BaseModel):
    name: str
    url: str
    token: str | None = None


SECRET = "SUPER-SECRET-TOKEN-XYZ123"


async def test_malformed_body_does_not_echo_back_a_submitted_secret():
    router = APIRouter()

    @router.post("/v1/hosts")
    async def register(reg: _Registration) -> _Registration:
        return reg

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        # `url` bị thiếu, nhưng `token` mang một bí mật cụ thể — FastAPI mặc
        # định sẽ nhét nguyên `input` (bao gồm token) vào từng lỗi 422.
        resp = await c.post("/v1/hosts", json={"name": "gpu-2", "token": SECRET})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "bad_input"
    # Đúng chuẩn envelope của nền tảng, không phải shape `detail` mặc định của FastAPI.
    assert set(body.keys()) == {"code", "message", "trace_id"}
    assert SECRET not in resp.text
    # Vẫn phải nêu tên trường sai để còn debug được, chỉ là không được lộ giá trị.
    assert "url" in body["message"]


async def test_trace_id_is_generated_when_client_supplies_none():
    router = APIRouter()

    @router.get("/echo")
    async def echo():
        return {"seen": get_trace_id()}

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/echo")
    # Cái log nhìn thấy và cái trả về header phải là một, nếu không thì vô dụng.
    assert resp.json()["seen"] == resp.headers["x-trace-id"]
    assert len(resp.headers["x-trace-id"]) == 32


async def test_incoming_trace_id_header_is_reused_not_replaced():
    router = APIRouter()

    @router.get("/echo")
    async def echo():
        return {"seen": get_trace_id()}

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/echo", headers={"x-trace-id": "trace-tu-gateway"})
    assert resp.json()["seen"] == "trace-tu-gateway"
    assert resp.headers["x-trace-id"] == "trace-tu-gateway"


def test_trace_id_defaults_to_dash_and_can_be_set():
    assert get_trace_id() == "-"
    set_trace_id("abc123")
    assert get_trace_id() == "abc123"


def test_settings_read_env_with_vypq_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VYPQ_SERVICE_NAME", "ocr")
    monkeypatch.setenv("VYPQ_PORT", "8123")
    s = BaseServiceSettings()
    assert s.service_name == "ocr"
    assert s.port == 8123
