"""Xác nhận mọi route /v1 của gateway đòi bearer token, còn /health, /ready và
/metrics thì không — cùng cách model-host đã pin (apps/model-host/tests/test_api.py).

Trước bản sửa này, GET /v1/discovery/hosts phát token của mọi host GPU đang
thuê cho bất kỳ ai chạm được cổng, và POST /v1/hosts cho phép ai đó trỏ lại
một host đang thuê sang URL của họ — đó chính là lỗ hổng review tổng B1 nêu ra.
"""

import httpx
import pytest
from gateway.api.discovery import build_discovery_router
from gateway.api.hosts import build_hosts_router
from gateway.api.invoke import build_invoke_router
from gateway.api.runs import build_runs_router
from gateway.api.services import build_services_router
from gateway.db.models import Base
from gateway.main import build_app
from gateway.proxy import SyncProxy
from gateway.registry.services import ServiceRegistry
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_core.metrics import build_metrics_router

TOKEN = "sekret"

V1_GET_ROUTES = ["/v1/hosts", "/v1/discovery/hosts", "/v1/services", "/v1/runs"]


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = GatewaySettings(service_name="gateway", token=TOKEN)
    registry = ServiceRegistry([])
    proxy = SyncProxy(registry, factory)
    app = build_app(
        factory,
        settings,
        routers=[
            build_hosts_router(factory, settings),
            build_discovery_router(factory, settings),
            build_services_router(registry, settings),
            build_invoke_router(proxy, settings),
            build_runs_router(factory, settings),
            build_metrics_router(),
        ],
    )
    yield app
    await registry.aclose()
    await proxy.aclose()
    await engine.dispose()


def _client(app, **headers) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers
    )


@pytest.mark.parametrize("path", V1_GET_ROUTES)
async def test_v1_route_without_token_is_rejected(ctx, path):
    async with _client(ctx) as c:
        resp = await c.get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path", V1_GET_ROUTES)
async def test_v1_route_with_wrong_token_is_rejected(ctx, path):
    async with _client(ctx, Authorization="Bearer sai") as c:
        resp = await c.get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path", V1_GET_ROUTES)
async def test_v1_route_with_correct_token_is_accepted(ctx, path):
    async with _client(ctx, Authorization=f"Bearer {TOKEN}") as c:
        resp = await c.get(path)
    assert resp.status_code != 401


async def test_invoke_post_without_token_is_rejected(ctx):
    # POST /v1/invoke với body rỗng/không hợp lệ VẪN phải bị chặn ở tầng auth
    # trước khi chạm tới validation của handler — nếu không, người gọi biết
    # ngay route tồn tại và chờ đúng shape body mà không cần token.
    async with _client(ctx) as c:
        resp = await c.post("/v1/invoke", json={"service": "ocr"})
    assert resp.status_code == 401


async def test_delete_host_without_token_is_rejected(ctx):
    async with _client(ctx) as c:
        resp = await c.delete("/v1/hosts/gpu-1")
    assert resp.status_code == 401


async def test_health_does_not_require_token(ctx):
    async with _client(ctx) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200


async def test_ready_does_not_require_token(ctx):
    async with _client(ctx) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 200


async def test_metrics_does_not_require_token(ctx):
    async with _client(ctx) as c:
        resp = await c.get("/metrics")
    assert resp.status_code == 200


async def test_docs_are_not_exposed_by_default(ctx):
    async with _client(ctx, Authorization=f"Bearer {TOKEN}") as c:
        for path in ("/docs", "/openapi.json", "/redoc"):
            assert (await c.get(path)).status_code == 404, path


def test_settings_refuse_empty_token():
    with pytest.raises(ValueError):
        GatewaySettings(service_name="gateway", token="")
