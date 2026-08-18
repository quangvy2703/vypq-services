from enum import Enum

from pydantic import BaseModel, Field


class Task(str, Enum):
    OCR = "ocr"
    ASR = "asr"


class ModelKind(str, Enum):
    OPENSOURCE = "opensource"
    FINETUNED = "finetuned"


class ErrorCode(str, Enum):
    BAD_INPUT = "bad_input"
    MODEL_UNAVAILABLE = "model_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_ERROR = "upstream_error"
    CIRCUIT_OPEN = "circuit_open"
    INTERNAL = "internal"


class HealthStatus(str, Enum):
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
