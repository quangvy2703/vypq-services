from typing import Any

from pydantic import BaseModel, Field, model_validator

from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

RawOutput = RawOcrOutput | RawAsrOutput

_OUTPUT_BY_TASK: dict[Task, type[BaseModel]] = {
    Task.OCR: RawOcrOutput,
    Task.ASR: RawAsrOutput,
}


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

    @model_validator(mode="before")
    @classmethod
    def _resolve_output_by_task(cls, data: Any) -> Any:
        """Chọn kiểu output theo `task`, không để pydantic tự đoán.

        RawOcrOutput và RawAsrOutput đều có field mặc định rỗng, nên payload `{}`
        khớp member đầu tiên của union bất kể task là gì — model trả rỗng (ảnh
        không có chữ) sẽ âm thầm ra RawOcrOutput ngay cả khi task=ASR. Payload
        mang cả 'boxes' lẫn 'segments' còn tệ hơn: một nửa dữ liệu bị vứt lặng lẽ.
        """
        if not isinstance(data, dict):
            return data
        raw_task, output = data.get("task"), data.get("output")
        if raw_task is None or not isinstance(output, dict):
            return data
        expected = _OUTPUT_BY_TASK[Task(raw_task)]
        allowed = set(expected.model_fields)
        unexpected = set(output) - allowed
        if unexpected:
            # RawOcrOutput/RawAsrOutput mặc định bỏ qua field lạ (extra="ignore"),
            # nên nếu không chặn ở đây, field của task kia sẽ bị vứt lặng lẽ thay
            # vì báo lỗi ngay.
            raise ValueError(
                f"output có field {sorted(unexpected)} không hợp lệ với "
                f"task={raw_task!r} (chỉ chấp nhận {sorted(allowed)})"
            )
        return {**data, "output": expected.model_validate(output)}
