from typing import Protocol

from vypq_contracts.asr import RawAsrOutput


class AsrBackend(Protocol):
    async def infer(self, image: bytes, model_id: str) -> RawAsrOutput: ...
