from typing import Any

from pydantic import BaseModel, Field

from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

# Union thường: RawOcrOutput có 'boxes', RawAsrOutput có 'segments' — hai
# trường rời nhau nên pydantic phân biệt được mà không cần discriminator.
RawOutput = RawOcrOutput | RawAsrOutput


class ModelInfo(BaseModel):
    id: str
    task: Task
    kind: ModelKind
    runner: str
    loaded: bool = False
    available: bool = True
    vram_mb: int = 0
    base: str | None = None
    trained_on: str | None = None


class ModelsResponse(BaseModel):
    host_name: str
    models: list[ModelInfo] = Field(default_factory=list)


class InferRequest(BaseModel):
    model_id: str
    input_uri: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class InferTiming(BaseModel):
    load_ms: int = 0
    infer_ms: int


class InferResponse(BaseModel):
    model_id: str
    task: Task
    output: RawOutput
    timing: InferTiming
