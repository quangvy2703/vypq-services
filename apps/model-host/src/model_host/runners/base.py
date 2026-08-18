from typing import Protocol

from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput

from model_host.spec import ModelSpec


class ModelRunner(Protocol):
    task: Task

    def load(self, spec: ModelSpec) -> None: ...
    def unload(self) -> None: ...
    def predict(self, data: bytes, params: dict) -> RawOcrOutput | RawAsrOutput: ...
