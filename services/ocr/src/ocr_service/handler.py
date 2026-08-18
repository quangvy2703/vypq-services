import time

from vypq_contracts.ocr import OcrResponse

from ocr_service.backend.base import OcrBackend
from ocr_service.pipeline.postprocess import to_result
from ocr_service.pipeline.preprocess import prepare_image


class OcrHandler:
    """Logic dùng chung cho cả HTTP lẫn Kafka worker."""

    def __init__(self, backend: OcrBackend, *, default_model: str, max_side: int = 2000) -> None:
        self._backend = backend
        self._default_model = default_model
        self._max_side = max_side

    async def run(
        self, image: bytes, model_version: str | None, trace_id: str
    ) -> OcrResponse:
        model_id = model_version or self._default_model
        started = time.monotonic()
        prepared = prepare_image(image, max_side=self._max_side)
        raw = await self._backend.infer(prepared.data, model_id)
        result = to_result(raw, prepared.scale)
        return OcrResponse(
            trace_id=trace_id,
            model_version=model_id,
            result=result,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
