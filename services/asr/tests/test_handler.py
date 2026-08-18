import pytest
from asr_service.backend.fake import FakeAsrBackend
from asr_service.handler import AsrHandler
from vypq_contracts.asr import RawAsrOutput, Segment


def _raw(*texts: str) -> RawAsrOutput:
    return RawAsrOutput(
        segments=[
            Segment(start=float(i), end=float(i) + 1.0, text=t) for i, t in enumerate(texts)
        ]
    )


async def test_run_returns_response_with_transcript_and_segments():
    handler = AsrHandler(FakeAsrBackend(_raw("xin", "chào")), default_model="m1")
    resp = await handler.run(b"payload", model_version=None, trace_id="t1")
    assert resp.result.text == "xin chào"
    assert len(resp.result.segments) == 1
    assert resp.trace_id == "t1"
    assert resp.model_version == "m1"
    assert resp.latency_ms >= 0


async def test_run_uses_requested_model_version():
    backend = FakeAsrBackend(_raw("a"))
    handler = AsrHandler(backend, default_model="m1")
    resp = await handler.run(b"payload", model_version="m2", trace_id="t1")
    assert resp.model_version == "m2"
    assert backend.calls[0][1] == "m2"


async def test_backend_error_propagates_unchanged():
    handler = AsrHandler(FakeAsrBackend(error=RuntimeError("hỏng")), default_model="m1")
    with pytest.raises(RuntimeError):
        await handler.run(b"payload", model_version=None, trace_id="t1")
