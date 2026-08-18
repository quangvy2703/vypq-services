from typing import Any

from pydantic import BaseModel, Field
from vypq_contracts.common import ErrorCode, Task


class InferenceRequested(BaseModel):
    task: Task
    input_uri: str
    model_version: str | None = None
    eval_job_id: str | None = None
    dataset_item_id: str | None = None


class InferenceCompleted(BaseModel):
    task: Task
    model_version: str
    input_uri: str
    output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int
    eval_job_id: str | None = None
    dataset_item_id: str | None = None


class InferenceFailed(BaseModel):
    task: Task
    input_uri: str
    code: ErrorCode
    message: str
    attempts: int
    model_version: str | None = None
    eval_job_id: str | None = None
    dataset_item_id: str | None = None
