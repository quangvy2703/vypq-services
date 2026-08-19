import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from vypq_core.app import create_app
from vypq_core.logging import get_logger
from vypq_core.metrics import build_metrics_router

from gateway.settings import GatewaySettings

log = get_logger(__name__)


def build_app(
    session_factory,
    settings: GatewaySettings,
    routers: Sequence[APIRouter] = (),
    lifespan=None,
) -> FastAPI:
    return create_app(settings, routers=list(routers), lifespan=lifespan)


def background_lifespan(
    tasks: Sequence[Callable[[], Awaitable[None]]],
    on_shutdown: Sequence[Callable[[], Awaitable[None]]],
    on_startup: Sequence[Callable[[], Awaitable[None]]] = (),
):
    """Chạy các vòng nền suốt vòng đời app, huỷ sạch khi tắt.

    MỖI vòng là một task riêng được theo dõi. Gộp nhiều vòng vào một task rồi
    `gather` bên trong là sai: gather KHÔNG huỷ các nhánh còn lại khi một nhánh
    ném lỗi, nên nhánh sống sót thành task mồ côi — không nằm trong danh sách
    theo dõi, không bị huỷ lúc tắt, và vẫn chạy sau khi app đã đóng.
    """

    @asynccontextmanager
    async def lifespan(_app):
        for hook in on_startup:
            await hook()
        running = [asyncio.create_task(_guard(t)) for t in tasks]
        try:
            yield
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            for hook in on_shutdown:
                await hook()

    return lifespan


async def _guard(task: Callable[[], Awaitable[None]]) -> None:
    # Vòng nền chết KHÔNG được kéo theo API. Poller hỏng thì host dần quá hạn
    # và biến mất khỏi định tuyến — đó là hỏng an toàn. API sập thì mất tất.
    try:
        await task()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("background_task_died", error=str(exc))


def create_gateway() -> FastAPI:
    from vypq_events.producer import EventProducer

    from gateway.api.discovery import build_discovery_router
    from gateway.api.hosts import build_hosts_router
    from gateway.api.invoke import build_invoke_router
    from gateway.api.runs import build_runs_router
    from gateway.api.services import build_services_router
    from gateway.db.engine import make_engine, make_session_factory
    from gateway.dispatcher import Dispatcher
    from gateway.proxy import SyncProxy
    from gateway.registry.poller import HostPoller
    from gateway.registry.services import ServiceRegistry, load_services
    from gateway.result_consumer import build_result_consumers

    settings = GatewaySettings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)

    service_registry = ServiceRegistry(load_services(settings.services_path))
    poller = HostPoller(factory, settings)
    producer = EventProducer(settings.brokers)
    proxy = SyncProxy(service_registry, factory)
    dispatcher = Dispatcher(service_registry, producer)
    consumers = build_result_consumers(factory, settings, producer, service_registry)

    async def refresh_services() -> None:
        while True:
            await service_registry.refresh()
            await asyncio.sleep(settings.poll_interval_s)

    async def start_messaging() -> None:
        # Khởi động trước khi các vòng chạy, để mỗi consumer.run có thể là một
        # task riêng được theo dõi thay vì gộp chung một task.
        await producer.start()
        for consumer in consumers:
            await consumer.start()

    async def shutdown() -> None:
        for consumer in consumers:
            await consumer.stop()
        await producer.stop()
        await service_registry.aclose()
        await proxy.aclose()
        await engine.dispose()

    return build_app(
        factory,
        settings,
        routers=[
            build_hosts_router(factory, settings),
            build_discovery_router(factory, settings),
            build_services_router(service_registry),
            build_invoke_router(proxy, dispatcher),
            build_runs_router(factory),
            build_metrics_router(),
        ],
        lifespan=background_lifespan(
            [poller.run, refresh_services, *(c.run for c in consumers)],
            on_shutdown=[shutdown],
            on_startup=[start_messaging],
        ),
    )


app = create_gateway()
