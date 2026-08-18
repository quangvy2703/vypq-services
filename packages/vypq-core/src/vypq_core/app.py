import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from vypq_contracts.common import ErrorCode, HealthResponse, HealthStatus
from vypq_core.config import BaseServiceSettings
from vypq_core.errors import _envelope, install_error_handlers
from vypq_core.logging import get_logger, set_trace_id, setup_logging

log = get_logger(__name__)

HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]

_WORST = {HealthStatus.OK: 0, HealthStatus.DEGRADED: 1, HealthStatus.DOWN: 2}


def create_app(
    settings: BaseServiceSettings,
    *,
    routers: Sequence[APIRouter] = (),
    readiness: Mapping[str, HealthCheck] | None = None,
    lifespan=None,
) -> FastAPI:
    setup_logging(settings.log_level)
    app = FastAPI(title=settings.service_name, version=settings.version, lifespan=lifespan)
    checks: Mapping[str, HealthCheck] = readiness or {}

    @app.middleware("http")
    async def _trace_middleware(request: Request, call_next):
        # Chỉ gán trace_id (dùng cho log + error envelope) khi caller đã cung cấp
        # sẵn qua header — nếu không, get_trace_id() giữ nguyên sentinel "-",
        # khớp với hợp đồng "trace_id: null" khi client không truyền trace.
        incoming = request.headers.get("x-trace-id")
        if incoming:
            set_trace_id(incoming)
        trace = incoming or uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as exc:
            # An toàn bổ sung: với BaseHTTPMiddleware, Starlette đưa handler
            # đăng ký cho `Exception` lên ServerErrorMiddleware — middleware đó
            # gửi response xong vẫn "raise" lại exception gốc, khiến ASGI test
            # client (mặc định raise_app_exceptions=True) lộ traceback ra ngoài
            # thay vì trả JSONResponse. Bắt tại đây để đảm bảo hành vi ổn định,
            # không phụ thuộc backend ASGI đang chạy.
            log.exception("unhandled_error", error=str(exc))
            response = _envelope(ErrorCode.INTERNAL, "internal server error", 500)
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
            detail=detail,
        )
        code = 200 if overall is HealthStatus.OK else 503
        return JSONResponse(status_code=code, content=body.model_dump(mode="json"))

    for router in routers:
        app.include_router(router)

    install_error_handlers(app)
    return app
