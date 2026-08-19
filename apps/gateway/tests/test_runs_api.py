import httpx
import pytest
from gateway.api.runs import build_runs_router
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.main import build_app
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.gateway import InvokeMode, RunStatus


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory, GatewaySettings(service_name="gateway"),
                    routers=[build_runs_router(factory)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory
    await engine.dispose()


async def _seed(factory, n=3, service="ocr", status=RunStatus.OK):
    async with factory() as s:
        for i in range(n):
            await RunRepo(s).record(
                trace_id=f"{service}-{status.value}-{i}", service=service,
                model_version="m1", mode=InvokeMode.SYNC, status=status,
                input_uri=None, output={"ok": True}, latency_ms=10, error=None,
            )


async def test_list_runs_returns_total_and_page(ctx):
    client, factory = ctx
    await _seed(factory, n=5)
    body = (await client.get("/v1/runs?limit=2")).json()
    assert body["total"] == 5
    assert len(body["runs"]) == 2


async def test_filter_by_service(ctx):
    client, factory = ctx
    await _seed(factory, n=2, service="ocr")
    await _seed(factory, n=3, service="asr")
    assert (await client.get("/v1/runs?service=asr")).json()["total"] == 3


async def test_filter_by_trace_id(ctx):
    # Đây là cách duy nhất người gọi async tìm lại kết quả của mình.
    client, factory = ctx
    await _seed(factory, n=2, service="ocr")
    body = (await client.get("/v1/runs?trace_id=ocr-ok-0")).json()
    assert body["total"] == 1


async def test_filter_by_status(ctx):
    client, factory = ctx
    await _seed(factory, n=2, status=RunStatus.OK)
    await _seed(factory, n=1, status=RunStatus.FAILED)
    assert (await client.get("/v1/runs?status=failed")).json()["total"] == 1


async def test_get_one_run(ctx):
    client, factory = ctx
    await _seed(factory, n=1)
    run_id = (await client.get("/v1/runs")).json()["runs"][0]["id"]
    assert (await client.get(f"/v1/runs/{run_id}")).status_code == 200


async def test_unknown_run_is_404(ctx):
    client, _factory = ctx
    assert (await client.get("/v1/runs/khong-co")).status_code == 404


async def test_invalid_status_filter_is_422(ctx):
    client, _factory = ctx
    assert (await client.get("/v1/runs?status=lung-tung")).status_code == 422
