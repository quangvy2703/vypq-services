from enum import StrEnum

from pydantic import BaseModel, Field


class Task(StrEnum):
    OCR = "ocr"
    ASR = "asr"


class ModelKind(StrEnum):
    OPENSOURCE = "opensource"
    FINETUNED = "finetuned"


class ErrorCode(StrEnum):
    BAD_INPUT = "bad_input"
    MODEL_UNAVAILABLE = "model_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_ERROR = "upstream_error"
    CIRCUIT_OPEN = "circuit_open"
    INTERNAL = "internal"


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    trace_id: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    service: str
    version: str
    detail: dict[str, str] = Field(default_factory=dict)
