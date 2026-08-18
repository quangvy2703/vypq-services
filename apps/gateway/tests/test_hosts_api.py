import httpx
import pytest
from gateway.api.hosts import build_hosts_router
from gateway.db.models import Base
from gateway.main import build_app
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = GatewaySettings(service_name="gateway")
    app = build_app(factory, settings, routers=[build_hosts_router(factory, settings)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c
    await engine.dispose()


async def test_register_then_list(client):
    resp = await client.post(
        "/v1/hosts", json={"name": "gpu-1", "url": "https://a.ngrok.app", "token": "t"}
    )
    assert resp.status_code == 201
    listed = (await client.get("/v1/hosts")).json()["hosts"]
    assert [h["name"] for h in listed] == ["gpu-1"]
    assert listed[0]["healthy"] is False       # chưa poll thì chưa khoẻ


async def test_listing_never_leaks_the_token(client):
    await client.post(
        "/v1/hosts", json={"name": "gpu-1", "url": "http://h:9000", "token": "bi-mat"}
    )
    body = (await client.get("/v1/hosts")).text
    assert "bi-mat" not in body


async def test_reregister_updates_url(client):
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://cu:9000"})
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://moi:9000"})
    listed = (await client.get("/v1/hosts")).json()["hosts"]
    assert len(listed) == 1
    assert listed[0]["url"] == "http://moi:9000"


async def test_delete_host(client):
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://h:9000"})
    assert (await client.delete("/v1/hosts/gpu-1")).status_code == 204
    assert (await client.get("/v1/hosts")).json()["hosts"] == []


async def test_delete_unknown_host_is_404(client):
    assert (await client.delete("/v1/hosts/khong-co")).status_code == 404


async def test_register_rejects_missing_url(client):
    assert (await client.post("/v1/hosts", json={"name": "gpu-1"})).status_code == 422


async def test_health_is_available(client):
    assert (await client.get("/health")).status_code == 200
