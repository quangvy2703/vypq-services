from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from vypq_contracts.common import ErrorCode, ErrorResponse

from vypq_core.logging import get_logger, get_trace_id

log = get_logger(__name__)


class ServiceError(Exception):
    def __init__(self, code: ErrorCode, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _envelope(code: ErrorCode, message: str, status: int) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, trace_id=_trace_or_none())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _trace_or_none() -> str | None:
    trace = get_trace_id()
    return None if trace == "-" else trace


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _handle_service_error(_request: Request, exc: ServiceError):
        log.warning("service_error", code=exc.code.value, message=exc.message)
        return _envelope(exc.code, exc.message, exc.http_status)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception):
        # Ghi traceback vào log, nhưng không bao giờ trả ra ngoài.
        log.exception("unhandled_error", error=str(exc))
        return _envelope(ErrorCode.INTERNAL, "internal server error", 500)
