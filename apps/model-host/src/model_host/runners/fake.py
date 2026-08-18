from vypq_contracts.asr import RawAsrOutput, Segment
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox

from model_host.spec import ModelSpec


class FakeOcrRunner:
    """Runner không cần GPU. Dùng cho test và cho việc chạy thử toàn stack."""

    task = Task.OCR

    def __init__(self) -> None:
        self._spec: ModelSpec | None = None

    def load(self, spec: ModelSpec) -> None:
        self._spec = spec

    def unload(self) -> None:
        self._spec = None

    def predict(self, data: bytes, params: dict) -> RawOcrOutput:
        # Trả box cố định, không phụ thuộc nội dung ảnh — đủ để kiểm hợp đồng.
        return RawOcrOutput(
            boxes=[
                TextBox(id=0, polygon=[(10, 10), (110, 10), (110, 40), (10, 40)],
                        text="XIN CHÀO", confidence=0.99),
                TextBox(id=1, polygon=[(10, 50), (90, 50), (90, 80), (10, 80)],
                        text="thế giới", confidence=0.95),
            ]
        )


class FakeAsrRunner:
    task = Task.ASR

    def load(self, spec: ModelSpec) -> None:
        self._spec = spec

    def unload(self) -> None:
        self._spec = None

    def predict(self, data: bytes, params: dict) -> RawAsrOutput:
        return RawAsrOutput(
            segments=[
                Segment(start=0.0, end=1.2, text="xin chào"),
                Segment(start=1.4, end=2.9, text="thế giới"),
            ]
        )
