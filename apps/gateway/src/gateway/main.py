import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from vypq_contracts.common import HealthStatus
from vypq_core.app import create_app
from vypq_core.logging import get_logger
from vypq_core.metrics import build_metrics_router

from gateway.settings import GatewaySettings

log = get_logger(__name__)

HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]


def build_app(
    session_factory,
    settings: GatewaySettings,
    routers: Sequence[APIRouter] = (),
    lifespan=None,
    readiness: Mapping[str, HealthCheck] | None = None,
) -> FastAPI:
    return create_app(
        settings,
        routers=list(routers),
        lifespan=lifespan,
        readiness=readiness,
        expose_docs=settings.expose_docs,
    )


def background_lifespan(
    tasks: Sequence[Callable[[], Awaitable[None]]],
    on_shutdown: Sequence[Callable[[], Awaitable[None]]],
    on_startup: Sequence[Callable[[], Awaitable[None]]] = (),
    task_handles: list[asyncio.Task] | None = None,
):
    """Chạy các vòng nền suốt vòng đời app, huỷ sạch khi tắt.

    MỖI vòng là một task riêng được theo dõi. Gộp nhiều vòng vào một task rồi
    `gather` bên trong là sai: gather KHÔNG huỷ các nhánh còn lại khi một nhánh
    ném lỗi, nên nhánh sống sót thành task mồ côi — không nằm trong danh sách
    theo dõi, không bị huỷ lúc tắt, và vẫn chạy sau khi app đã đóng.

    `task_handles`, nếu có, được điền (in-place, cùng thứ tự với `tasks`) bằng
    các asyncio.Task vừa tạo lúc startup. Đây là cách duy nhất để code BÊN
    NGOÀI closure này (ví dụ một readiness check) biết một vòng nền cụ thể có
    còn sống hay không — `running` ở dưới là biến cục bộ của lifespan.
    """

    @asynccontextmanager
    async def lifespan(_app):
        for hook in on_startup:
            await hook()
        running = [asyncio.create_task(_guard(t)) for t in tasks]
        if task_handles is not None:
            task_handles[:] = running
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


def consumer_readiness(consumers: Sequence, task_handles: list, offset: int) -> HealthCheck:
    """Readiness check cho các result consumer, phát hiện task NỀN đã chết.

    _guard() bên trên nuốt mọi exception của vòng nền rồi im lặng sống tiếp —
    đúng cho poller/refresh_services (hỏng an toàn: host quá hạn rồi biến
    mất). Nhưng với result consumer, task chết nghĩa là ingestion của topic đó
    dừng HẲN mà /ready vẫn báo 200 vì trước đây create_gateway() không truyền
    readiness= gì cả — im lặng, vĩnh viễn, không ai biết. `task_handles` được
    background_lifespan() điền lúc startup (xem docstring ở đó); `offset` là
    số task KHÔNG PHẢI consumer đứng trước trong cùng danh sách `tasks` (ví
    dụ poller.run, refresh_services), để lấy đúng lát cắt ứng với `consumers`.
    """

    async def check() -> tuple[HealthStatus, str]:
        handles = task_handles[offset:]
        if len(handles) < len(consumers):
            # Lifespan chưa chạy xong startup — chưa có gì để kiểm.
            return HealthStatus.OK, "chưa khởi động"
        dead = [c._dlq_topic for c, t in zip(consumers, handles, strict=True) if t.done()]
        if dead:
            return HealthStatus.DOWN, f"consumer(s) đã chết: {', '.join(dead)}"
        return HealthStatus.OK, "đang chạy"

    return check


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
    proxy = SyncProxy(
        service_registry, factory,
        max_download_mb=settings.max_download_mb,
        fetch_deadline_s=settings.fetch_deadline_s,
    )
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

    core_tasks = [poller.run, refresh_services]
    task_handles: list[asyncio.Task] = []

    return build_app(
        factory,
        settings,
        routers=[
            build_hosts_router(factory, settings),
            build_discovery_router(factory, settings),
            build_services_router(service_registry, settings),
            build_invoke_router(proxy, settings, dispatcher),
            build_runs_router(factory, settings),
            build_metrics_router(),
        ],
        readiness={
            "result_consumers": consumer_readiness(
                consumers, task_handles, len(core_tasks)
            )
        },
        lifespan=background_lifespan(
            [*core_tasks, *(c.run for c in consumers)],
            on_shutdown=[shutdown],
            on_startup=[start_messaging],
            task_handles=task_handles,
        ),
    )


app = create_gateway()
