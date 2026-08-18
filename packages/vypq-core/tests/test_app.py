import httpx
import pytest
from fastapi import APIRouter

from vypq_contracts.common import ErrorCode, HealthStatus
from vypq_core.app import create_app
from vypq_core.config import BaseServiceSettings
from vypq_core.errors import ServiceError
from vypq_core.logging import get_trace_id, set_trace_id

SETTINGS = BaseServiceSettings(service_name="demo", version="9.9.9")


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


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
    assert resp.status_code == 422
    assert resp.json() == {"code": "bad_input", "message": "ảnh hỏng", "trace_id": None}


async def test_unexpected_exception_is_masked_as_internal():
    router = APIRouter()

    @router.get("/crash")
    async def crash():
        raise RuntimeError("chi tiết nội bộ không được lộ ra")

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/crash")
    body = resp.json()
    assert resp.status_code == 500
    assert body["code"] == "internal"
    assert "chi tiết nội bộ" not in body["message"]


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
