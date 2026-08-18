import io

import pytest
from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.worker import OcrWorkerHandler, group_id
from PIL import Image
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.http_client import UpstreamError
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.schemas.inference import InferenceRequested


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def _raw() -> RawOcrOutput:
    return RawOcrOutput(
        boxes=[TextBox(id=0, polygon=[(0, 0), (9, 0), (9, 9), (0, 9)], text="HÓA ĐƠN")]
    )


def _envelope(model_version: str | None = None) -> RawEnvelope:
    env = EventEnvelope[InferenceRequested].new(
        "inference.requested",
        InferenceRequested(
            task=Task.OCR,
            input_uri="https://minio/a.png",
            model_version=model_version,
            eval_job_id="e1",
            dataset_item_id="item-7",
        ),
    )
    return RawEnvelope.model_validate_json(env.model_dump_json())


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish(self, topic, envelope, key=None):
        self.published.append((topic, envelope, key))


async def _fetch(_uri: str) -> bytes:
    return _png()


def test_group_id_is_default_when_no_model_version_forced():
    assert group_id("ocr", None) == "ocr-default"


def test_group_id_includes_forced_model_version():
    # Mỗi model version một consumer group → cùng event được mọi model xử lý.
    assert group_id("ocr", "vietocr-ft-invoice") == "ocr-vietocr-ft-invoice"


async def test_worker_publishes_completed_event_to_result_topic():
    producer = FakeProducer()
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(_raw()), default_model="m1"),
        producer,
        forced_model=None,
        fetch=_fetch,
    )
    envelope = _envelope()
    await worker(envelope)

    topic, published, key = producer.published[0]
    assert topic == "infer.ocr.results"
    assert key == envelope.trace_id
    assert published.payload.model_version == "m1"
    assert published.payload.output["full_text"] == "HÓA ĐƠN"
    assert published.payload.eval_job_id == "e1"
    assert published.payload.dataset_item_id == "item-7"
    assert published.trace_id == envelope.trace_id


async def test_event_model_version_is_used_when_nothing_is_forced():
    backend = FakeOcrBackend(_raw())
    worker = OcrWorkerHandler(
        OcrHandler(backend, default_model="m1"), FakeProducer(), forced_model=None, fetch=_fetch
    )
    await worker(_envelope(model_version="m2"))
    assert backend.calls[0][1] == "m2"


async def test_forced_model_overrides_the_event_field():
    backend = FakeOcrBackend(_raw())
    worker = OcrWorkerHandler(
        OcrHandler(backend, default_model="m1"),
        FakeProducer(),
        forced_model="vietocr-ft",
        fetch=_fetch,
    )
    await worker(_envelope(model_version="m2"))
    assert backend.calls[0][1] == "vietocr-ft"


async def test_upstream_error_is_not_swallowed():
    # Worker phải để lỗi bay lên EventConsumer, nếu không consumer sẽ không
    # bao giờ biết mà pause — và message sẽ rơi vào DLQ.
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(error=UpstreamError("gpu chết")), default_model="m1"),
        FakeProducer(),
        forced_model=None,
        fetch=_fetch,
    )
    with pytest.raises(UpstreamError):
        await worker(_envelope())


async def test_nothing_is_published_when_inference_fails():
    producer = FakeProducer()
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(error=UpstreamError("gpu chết")), default_model="m1"),
        producer,
        forced_model=None,
        fetch=_fetch,
    )
    with pytest.raises(UpstreamError):
        await worker(_envelope())
    assert producer.published == []
