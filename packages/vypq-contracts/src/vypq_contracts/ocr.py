from pydantic import BaseModel, Field

Polygon = list[tuple[float, float]]


class TextBox(BaseModel):
    id: int
    polygon: Polygon = Field(min_length=4)
    text: str
    confidence: float | None = None
    ignore: bool = False


class RawOcrOutput(BaseModel):
    """Kết quả thô từ model-host: chỉ có box, chưa sắp thứ tự đọc."""

    boxes: list[TextBox] = Field(default_factory=list)


class OcrResult(BaseModel):
    """Kết quả đã qua postprocess của service."""

    full_text: str
    boxes: list[TextBox] = Field(default_factory=list)


class OcrRequest(BaseModel):
    image_uri: str | None = None
    model_version: str | None = None


class OcrResponse(BaseModel):
    trace_id: str
    model_version: str
    result: OcrResult
    latency_ms: int
