import time

from vypq_contracts.asr import AsrResponse

from asr_service.backend.base import AsrBackend
from asr_service.pipeline.postprocess import to_result


class AsrHandler:
    def __init__(self, backend: AsrBackend, *, default_model: str) -> None:
        self._backend = backend
        self._default_model = default_model

    async def run(
        self, audio: bytes, model_version: str | None, trace_id: str
    ) -> AsrResponse:
        model_id = model_version or self._default_model
        started = time.monotonic()
        # Audio không cần resize như ảnh — gửi nguyên bytes sang model-host.
        raw = await self._backend.infer(audio, model_id)
        return AsrResponse(
            trace_id=trace_id,
            model_version=model_id,
            result=to_result(raw),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
