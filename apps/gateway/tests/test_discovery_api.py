from datetime import UTC, datetime, timedelta

import httpx
import pytest
from gateway.api.discovery import build_discovery_router
from gateway.db.models import Base, Host
from gateway.db.repo import HostRepo
from gateway.main import build_app
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.gateway import HostRegistration
from vypq_contracts.hosting import ModelInfo

SETTINGS = GatewaySettings(service_name="gateway", host_ttl_s=45.0)


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory, SETTINGS, routers=[build_discovery_router(factory, SETTINGS)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory
    await engine.dispose()


def _model() -> ModelInfo:
    return ModelInfo(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")


async def _healthy_host(factory, name="gpu-1", seen_ago_s=0.0):
    async with factory() as s:
        await HostRepo(s).upsert(
            HostRegistration(name=name, url="http://h:9000", token="bi-mat")
        )
        await HostRepo(s).mark_polled(name, healthy=True, models=[_model()], error=None)
        row = await s.get(Host, name)
        row.last_seen_at = datetime.now(UTC) - timedelta(seconds=seen_ago_s)
        await s.commit()


async def test_discovery_includes_the_token(ctx):
    client, factory = ctx
    await _healthy_host(factory)
    hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["token"] == "bi-mat"
    assert hosts[0]["healthy"] is True
    assert [m["id"] for m in hosts[0]["models"]] == ["m1"]


async def test_stale_host_is_served_as_unhealthy(ctx):
    # Poller treo -> cờ healthy đóng băng. Kiểm hạn lúc đọc để hỏng biểu hiện
    # thành "không có host", chứ không phải "mọi host đều khoẻ".
    client, factory = ctx
    await _healthy_host(factory, seen_ago_s=120.0)
    hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["healthy"] is False


async def test_host_seen_recently_stays_healthy(ctx):
    client, factory = ctx
    await _healthy_host(factory, seen_ago_s=10.0)
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"][0]["healthy"] is True


async def test_never_polled_host_is_unhealthy(ctx):
    client, factory = ctx
    async with factory() as s:
        await HostRepo(s).upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"][0]["healthy"] is False


async def test_empty_registry_returns_empty_list(ctx):
    client, _ = ctx
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"] == []
