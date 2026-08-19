from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
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

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_request: Request, exc: RequestValidationError):
        # KHÔNG trả exc.errors() nguyên bản: FastAPI nhét cả `input` vào từng mục,
        # nên một request đăng ký hỏng sẽ dội ngược token về cho chính người gửi.
        # Chỉ nói TRƯỜNG nào sai, tuyệt đối không nói người ta đã gửi giá trị gì.
        fields = sorted(
            ".".join(str(part) for part in error["loc"][1:]) or "body"
            for error in exc.errors()
        )
        log.warning("request_validation_failed", fields=fields)
        return _envelope(
            ErrorCode.BAD_INPUT, f"dữ liệu không hợp lệ: {', '.join(fields)}", 422
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception):
        # Ghi traceback vào log, nhưng không bao giờ trả ra ngoài.
        log.exception("unhandled_error", error=str(exc))
        return _envelope(ErrorCode.INTERNAL, "internal server error", 500)
