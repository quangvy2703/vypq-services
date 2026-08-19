import asyncio

import httpx
import pytest
from gateway.db.models import Base
from gateway.main import build_app
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class SpyTask:
    def __init__(self) -> None:
        self.rounds = 0

    async def run(self) -> None:
        while True:
            self.rounds += 1
            await asyncio.sleep(0.01)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_background_tasks_start_and_stop_with_the_app(factory):
    from gateway.main import background_lifespan

    spy = SpyTask()
    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([spy.run], on_shutdown=[]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            assert (await client.get("/health")).status_code == 200
            assert spy.rounds > 0
    # Sau khi thoát lifespan, vòng nền phải bị huỷ chứ không chạy tiếp.
    stopped_at = spy.rounds
    await asyncio.sleep(0.05)
    assert spy.rounds == stopped_at


async def test_a_crashing_background_task_does_not_take_the_app_down(factory):
    from gateway.main import background_lifespan

    async def explode() -> None:
        raise RuntimeError("vòng nền chết")

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([explode], on_shutdown=[]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            # Poller chết không được kéo theo API: /health vẫn phải trả lời.
            assert (await client.get("/health")).status_code == 200


async def test_shutdown_hooks_run(factory):
    from gateway.main import background_lifespan

    closed = []

    async def close() -> None:
        closed.append(True)

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([], on_shutdown=[close]),
    )
    async with app.router.lifespan_context(app):
        pass
    assert closed == [True]
