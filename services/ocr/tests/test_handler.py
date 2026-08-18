import io

import pytest
from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from PIL import Image
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.errors import ServiceError


def _png(width: int = 800, height: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _raw(*texts: str) -> RawOcrOutput:
    return RawOcrOutput(
        boxes=[
            TextBox(
                id=i,
                polygon=[
                    (10, 10 + i * 40),
                    (100, 10 + i * 40),
                    (100, 40 + i * 40),
                    (10, 40 + i * 40),
                ],
                text=t,
            )
            for i, t in enumerate(texts)
        ]
    )


async def test_run_returns_response_with_full_text():
    handler = OcrHandler(FakeOcrBackend(_raw("dòng một", "dòng hai")), default_model="m1")
    resp = await handler.run(_png(), model_version=None, trace_id="t1")
    assert resp.result.full_text == "dòng một\ndòng hai"
    assert resp.trace_id == "t1"
    assert resp.model_version == "m1"
    assert resp.latency_ms >= 0


async def test_run_uses_requested_model_version():
    backend = FakeOcrBackend(_raw("a"))
    handler = OcrHandler(backend, default_model="m1")
    resp = await handler.run(_png(), model_version="m2", trace_id="t1")
    assert resp.model_version == "m2"
    assert backend.calls[0][1] == "m2"


async def test_run_rescales_boxes_when_image_is_downsized():
    handler = OcrHandler(FakeOcrBackend(_raw("a")), default_model="m1", max_side=100)
    resp = await handler.run(_png(400, 200), model_version=None, trace_id="t1")
    # Ảnh bị thu 4 lần → toạ độ trả về phải nhân ngược lại 4.
    assert resp.result.boxes[0].polygon[0] == (40.0, 40.0)


async def test_run_rejects_non_image_input():
    handler = OcrHandler(FakeOcrBackend(_raw("a")), default_model="m1")
    with pytest.raises(ServiceError) as exc:
        await handler.run(b"day-khong-phai-anh", model_version=None, trace_id="t1")
    assert exc.value.http_status == 422


async def test_backend_error_propagates_unchanged():
    boom = RuntimeError("gpu chết")
    handler = OcrHandler(FakeOcrBackend(error=boom), default_model="m1")
    with pytest.raises(RuntimeError):
        await handler.run(_png(), model_version=None, trace_id="t1")
