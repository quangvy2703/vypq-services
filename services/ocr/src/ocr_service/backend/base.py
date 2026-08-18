from typing import Protocol

from vypq_contracts.ocr import RawOcrOutput


class OcrBackend(Protocol):
    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput: ...
