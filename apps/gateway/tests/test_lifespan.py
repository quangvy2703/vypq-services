import asyncio

import httpx
import pytest
from gateway.db.models import Base
from gateway.main import build_app
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.common import HealthStatus


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


async def test_a_crashing_task_does_not_orphan_the_survivor_which_is_cancelled_on_shutdown(
    factory,
):
    # Tái hiện đúng cách gateway.main.create_gateway() nối dây sau bản sửa: mỗi
    # consumer.run là một entry RIÊNG trong `tasks` (không gộp rồi gather như
    # `run_consumers` cũ), và việc start() được tách ra một hook `on_startup`
    # chạy trước khi các vòng được tạo task. Trước bản sửa, background_lifespan
    # không có tham số on_startup — không có nó thì không có cách nào tách
    # start() ra khỏi vòng lặp mà không gộp chúng vào một task duy nhất, tức là
    # bắt buộc phải rơi vào đúng antipattern gây mồ côi. Vì vậy lời gọi dưới đây
    # tự nó không thể diễn đạt được ở phiên bản trước khi sửa.
    from gateway.main import background_lifespan

    survivor = SpyTask()
    started = []

    async def start_things() -> None:
        started.append(True)

    async def explode() -> None:
        raise RuntimeError("vòng nền chết")

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan(
            [explode, survivor.run], on_shutdown=[], on_startup=[start_things]
        ),
    )
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
        # Nhánh explode chết không ngăn nhánh sống sót tiếp tục chạy: mỗi vòng
        # là một task riêng, không phải hai nhánh của cùng một gather.
        assert survivor.rounds > 0

    # Sau khi lifespan thoát, nhánh sống sót phải bị huỷ THẬT, không chạy mồ
    # côi: vì nó là task riêng được background_lifespan theo dõi, số vòng đứng
    # yên sau khi thoát. Đây chính là điều asyncio.gather nội bộ không đảm bảo
    # được — nó không huỷ nhánh còn sống khi nhánh kia ném lỗi thường.
    stopped_at = survivor.rounds
    await asyncio.sleep(0.05)
    assert survivor.rounds == stopped_at


async def test_on_startup_hooks_run_before_tasks_start(factory):
    from gateway.main import background_lifespan

    events = []

    async def startup_hook() -> None:
        events.append("startup")

    async def record_task() -> None:
        events.append("task")
        await asyncio.sleep(10)

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan(
            [record_task], on_shutdown=[], on_startup=[startup_hook]
        ),
    )
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.02)

    assert events[0] == "startup"
    assert "task" in events


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


class _FakeConsumer:
    """Chỉ mang đúng thuộc tính consumer_readiness() cần, không phải
    EventConsumer/Kafka thật — readiness check chỉ đọc `_dlq_topic`."""

    def __init__(self, dlq_topic: str) -> None:
        self._dlq_topic = dlq_topic


class _FakeTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


async def test_consumer_readiness_is_ok_before_task_handles_are_populated():
    # Lúc app khởi động, lifespan chưa chạy tới đoạn tạo task -> task_handles
    # rỗng. Readiness không được báo DOWN cho một thứ chưa kịp bắt đầu.
    from gateway.main import consumer_readiness

    consumers = [_FakeConsumer("infer.ocr.dlq"), _FakeConsumer("infer.asr.dlq")]
    task_handles: list = []
    check = consumer_readiness(consumers, task_handles, offset=0)
    status, note = await check()
    assert status is HealthStatus.OK
    assert note == "chưa khởi động"


async def test_consumer_readiness_is_ok_while_every_consumer_task_is_alive():
    from gateway.main import consumer_readiness

    consumers = [_FakeConsumer("infer.ocr.dlq"), _FakeConsumer("infer.asr.dlq")]
    task_handles = [_FakeTask(done=False), _FakeTask(done=False), _FakeTask(done=False)]
    check = consumer_readiness(consumers, task_handles, offset=1)
    status, _note = await check()
    assert status is HealthStatus.OK


async def test_consumer_readiness_reports_degraded_once_a_consumer_task_has_died():
    # Bug gốc: EventConsumer.run() chết vì lỗi I/O broker (CommitFailedError do
    # rebalance, mất kết nối, ...) và create_gateway() trước đây không truyền
    # readiness= gì cả, nên /ready báo 200 mãi mãi trong khi ingestion đã chết
    # hẳn. task_handles[offset:] ứng với `consumers` theo đúng thứ tự — task
    # thứ hai (index 1) "chết" (done()=True) phải bị phát hiện.
    from gateway.main import consumer_readiness

    consumers = [_FakeConsumer("infer.ocr.dlq"), _FakeConsumer("infer.asr.dlq")]
    task_handles = [_FakeTask(done=False), _FakeTask(done=False), _FakeTask(done=True)]
    check = consumer_readiness(consumers, task_handles, offset=1)
    status, note = await check()
    assert status is HealthStatus.DOWN
    assert "infer.asr.dlq" in note


async def test_create_gateway_ready_endpoint_reports_degraded_when_a_consumer_dies(factory):
    # Đầu-đến-cuối qua /ready thật, không chỉ gọi thẳng consumer_readiness():
    # dựng app y hệt cách create_gateway() nối dây (background_lifespan +
    # readiness=), thay EventConsumer.run thật bằng một coroutine chết ngay
    # lập tức, và xác nhận GET /ready trả 503 + detail nói rõ topic nào chết.
    from gateway.main import background_lifespan, consumer_readiness

    consumers = [_FakeConsumer("infer.ocr.dlq")]

    async def dying_consumer_run() -> None:
        raise RuntimeError("mất kết nối broker")

    task_handles: list = []
    app = build_app(
        factory,
        GatewaySettings(service_name="gateway"),
        readiness={"result_consumers": consumer_readiness(consumers, task_handles, 0)},
        lifespan=background_lifespan(
            [dying_consumer_run], on_shutdown=[], task_handles=task_handles
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            resp = await client.get("/ready")
            assert resp.status_code == 503
            assert resp.json()["status"] == "degraded"
            assert "infer.ocr.dlq" in resp.json()["detail"]["result_consumers"]
