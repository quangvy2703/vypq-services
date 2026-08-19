from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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

TOKEN = "sekret"
SETTINGS = GatewaySettings(service_name="gateway", host_ttl_s=45.0, token=TOKEN)


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory, SETTINGS, routers=[build_discovery_router(factory, SETTINGS)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {TOKEN}"},
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


async def test_future_last_seen_is_served_as_unhealthy(ctx):
    # Đây là lệch đồng hồ, không phải chuyện độ tươi bình thường: last_seen_at
    # ở TƯƠNG LAI (nhiều replica gateway, hoặc NTP trôi) khiến hiệu số âm. Chỉ
    # kiểm tra `<= ttl` sẽ cho qua vô điều kiện, và host coi như khoẻ vĩnh viễn
    # dù nó có thể đã chết từ lâu. seen_ago_s âm nghĩa là last_seen_at ở tương lai.
    client, factory = ctx
    await _healthy_host(factory, seen_ago_s=-30.0)
    hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["healthy"] is False


async def test_host_seen_exactly_at_ttl_boundary_is_healthy(ctx):
    # Biên `elapsed == ttl` được chọn là KHOẺ (<=, không phải <): quyết định có
    # chủ đích, không phải tình cờ, để pin lại hành vi ở đúng ranh giới. `now`
    # bị đóng băng vì so sánh giây trên đồng hồ tường (wall clock) thật sẽ luôn
    # trôi thêm vài micro giây giữa lúc ghi last_seen_at và lúc endpoint đọc
    # `datetime.now()`, khiến elapsed nhỉnh hơn ttl và bài test tự nhiên flaky.
    client, factory = ctx
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    async with factory() as s:
        await HostRepo(s).upsert(
            HostRegistration(name="gpu-1", url="http://h:9000", token="bi-mat")
        )
        await HostRepo(s).mark_polled("gpu-1", healthy=True, models=[_model()], error=None)
        row = await s.get(Host, "gpu-1")
        row.last_seen_at = fixed_now - timedelta(seconds=SETTINGS.host_ttl_s)
        await s.commit()

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    with patch("gateway.api.discovery.datetime", _FixedDateTime):
        hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["healthy"] is True
