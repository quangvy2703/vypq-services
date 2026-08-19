import pytest
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.registry.services import ServiceEntry, ServiceRegistry
from gateway.result_consumer import build_result_consumers, make_result_handler
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.common import Task
from vypq_contracts.gateway import RunStatus, ServiceInfo, ServiceState
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.schemas.inference import InferenceCompleted


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class FakeProducer:
    async def publish(self, topic, envelope, key=None):  # pragma: no cover
        pass


def _completed(model="m1", trace="t1") -> RawEnvelope:
    env = EventEnvelope[InferenceCompleted].new(
        "inference.completed",
        InferenceCompleted(
            task=Task.OCR, model_version=model, input_uri="s3://b/a.jpg",
            output={"full_text": "xin chào"}, latency_ms=33,
        ),
        trace_id=trace,
    )
    return RawEnvelope.model_validate_json(env.model_dump_json())


async def test_result_is_written_to_runs(factory):
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed())
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.OK
    assert runs[0].output["full_text"] == "xin chào"
    assert runs[0].latency_ms == 33


async def test_duplicate_delivery_writes_one_row(factory):
    # Kafka giao ít nhất một lần; cùng (trace, model) là cùng một kết quả.
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed())
    await handler(_completed())
    async with factory() as s:
        _runs, total = await RunRepo(s).list_runs()
    assert total == 1


async def test_shadow_run_results_are_separate_rows(factory):
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed(model="paddle-v4"))
    await handler(_completed(model="vietocr-ft"))
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 2
    assert {r.model_version for r in runs} == {"paddle-v4", "vietocr-ft"}


async def test_unparseable_payload_raises_so_the_consumer_dead_letters_it(factory):
    # Envelope hỏng là dữ liệu hỏng: phải ném để EventConsumer đẩy vào DLQ,
    # KHÔNG được nuốt — nuốt là mất kết quả mà không ai biết.
    handler = make_result_handler(factory, lambda task: "ocr")
    bad = RawEnvelope(
        event_id="e", event_type="inference.completed", trace_id="t",
        occurred_at="2026-08-18T00:00:00Z", payload={"khong": "dung shape"},
    )
    with pytest.raises(Exception):  # noqa: B017 - cố ý: bất kỳ exception nào cũng phải thoát ra
        await handler(bad)


async def test_build_result_consumers_targets_ocr_and_asr_topics(factory):
    registry = ServiceRegistry([])
    consumers = build_result_consumers(
        factory, GatewaySettings(), FakeProducer(), registry
    )
    topics = {(c._dlq_topic) for c in consumers}
    assert topics == {"infer.ocr.dlq", "infer.asr.dlq"}


async def test_service_name_for_skips_a_never_polled_service_ahead_of_the_match(factory):
    # ServiceState.info là None cho service gateway CHƯA TỪNG poll thành công.
    # Nếu service_name_for đọc .info.task trên một state như vậy trước khi tới
    # state khớp, nó ném AttributeError — không phải lỗi hạ tầng theo
    # default_is_retryable, nên EventConsumer sẽ dead-letter một kết quả lành.
    registry = ServiceRegistry(
        [
            ServiceEntry(name="untouched", base_url="http://untouched:9"),
            ServiceEntry(name="ocr", base_url="http://ocr:8001"),
        ]
    )
    registry._states["ocr"] = ServiceState(
        info=ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
        ),
        base_url="http://ocr:8001",
    )
    consumers = build_result_consumers(
        factory, GatewaySettings(), FakeProducer(), registry
    )
    ocr_consumer = next(c for c in consumers if c._dlq_topic == "infer.ocr.dlq")
    await ocr_consumer._handler(_completed())
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].service == "ocr"
