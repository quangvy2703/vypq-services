import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from vypq_contracts.common import HealthResponse, HealthStatus

from vypq_core.config import BaseServiceSettings
from vypq_core.errors import install_error_handlers
from vypq_core.logging import set_trace_id, setup_logging

HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]

_WORST = {HealthStatus.OK: 0, HealthStatus.DEGRADED: 1, HealthStatus.DOWN: 2}


def create_app(
    settings: BaseServiceSettings,
    *,
    routers: Sequence[APIRouter] = (),
    readiness: Mapping[str, HealthCheck] | None = None,
    lifespan=None,
    expose_docs: bool = True,
    expose_ready_detail: bool = True,
) -> FastAPI:
    setup_logging(settings.log_level)
    # /docs và /openapi.json nằm ngoài mọi router nên không dính dependency auth.
    # Service nào phơi ra Internet (model-host qua ngrok) phải tắt, nếu không là
    # trao không toàn bộ sơ đồ route và schema cho bất kỳ ai dò ra URL.
    app = FastAPI(
        title=settings.service_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    checks: Mapping[str, HealthCheck] = readiness or {}

    @app.middleware("http")
    async def _trace_middleware(request: Request, call_next):
        # Luôn gán, kể cả khi client không gửi: log và error envelope đều lấy từ
        # đây, nên gán có điều kiện sẽ làm mọi request thường mất trace trong log.
        # Middleware này KHÔNG bắt exception — việc đó thuộc install_error_handlers,
        # để chỉ có một chỗ dựng error envelope.
        trace = request.headers.get("x-trace-id") or uuid.uuid4().hex
        set_trace_id(trace)
        response = await call_next(request)
        response.headers["x-trace-id"] = trace
        return response

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        # Liveness: tiến trình còn sống là ok, không phụ thuộc upstream.
        return HealthResponse(
            status=HealthStatus.OK, service=settings.service_name, version=settings.version
        )

    @app.get("/ready")
    async def ready() -> JSONResponse:
        detail: dict[str, str] = {}
        worst = HealthStatus.OK
        for name, check in checks.items():
            status, note = await check()
            detail[name] = note
            if _WORST[status] > _WORST[worst]:
                worst = status
        # DOWN của một dependency = service degraded, không phải chết hẳn.
        overall = HealthStatus.OK if worst is HealthStatus.OK else HealthStatus.DEGRADED
        body = HealthResponse(
            status=overall,
            service=settings.service_name,
            version=settings.version,
            # /ready phải mở để probe hạ tầng gọi được, nên nó không qua auth.
            # Với service phơi ra Internet thì trạng thái ok/degraded là đủ; tên
            # check và chuỗi chẩn đoán bên trong không nên phát cho người lạ.
            detail=detail if expose_ready_detail else {},
        )
        code = 200 if overall is HealthStatus.OK else 503
        return JSONResponse(status_code=code, content=body.model_dump(mode="json"))

    for router in routers:
        app.include_router(router)

    install_error_handlers(app)
    return app
