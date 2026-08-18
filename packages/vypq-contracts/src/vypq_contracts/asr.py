from pydantic import BaseModel, Field


class Segment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str | None = None


class RawAsrOutput(BaseModel):
    segments: list[Segment] = Field(default_factory=list)


class AsrResult(BaseModel):
    text: str
    segments: list[Segment] = Field(default_factory=list)


class AsrRequest(BaseModel):
    audio_uri: str | None = None
    model_version: str | None = None


class AsrResponse(BaseModel):
    trace_id: str
    model_version: str
    result: AsrResult
    latency_ms: int
