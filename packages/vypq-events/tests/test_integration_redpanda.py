import asyncio
import time

import pytest
from vypq_contracts.common import Task
from vypq_core.http_client import UpstreamError
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import dlq_topic, request_topic

pytestmark = pytest.mark.slow
BROKERS = "localhost:9092"


async def test_roundtrip_through_real_redpanda():
    producer = EventProducer(BROKERS)
    await producer.start()
    received: list = []

    async def handler(env):
        received.append(env)

    consumer = EventConsumer(
        topic=request_topic(Task.OCR),
        group_id="test-ocr",
        handler=handler,
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=BROKERS,
    )
    await consumer.start()
    try:
        env = EventEnvelope[InferenceRequested].new(
            "inference.requested",
            InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg"),
        )
        await producer.publish(request_topic(Task.OCR), env)
        for _ in range(20):
            if await consumer.run_once():
                break
            await asyncio.sleep(0.5)
    finally:
        await consumer.stop()
        await producer.stop()

    assert len(received) == 1
    assert received[0].payload["input_uri"] == "s3://b/a.jpg"


async def test_retryable_failure_is_redelivered_and_nothing_is_lost():
    """Bảo đảm cốt lõi của cả nền tảng, và chỉ Kafka thật mới chứng minh được.

    FakeConsumer không mô phỏng việc giao lại sau seek() — nó pop nguyên batch ra
    khỏi list. Nên mọi test unit chỉ chứng minh được "có gọi seek", không chứng
    minh được "message quay lại". Đây là chỗ duy nhất kiểm được điều đó.
    """
    suffix = str(int(time.time() * 1000))
    topic = f"infer.ocr.requests.redeliver.{suffix}"
    producer = EventProducer(BROKERS)
    await producer.start()

    handled: list[str] = []
    failed_once: set[str] = set()

    async def handler(env):
        uri = env.payload["input_uri"]
        if uri == "u2" and uri not in failed_once:
            failed_once.add(uri)
            raise UpstreamError("gpu chết giữa chừng")
        handled.append(uri)

    clock_now = [0.0]
    consumer = EventConsumer(
        topic=topic,
        group_id=f"test-redeliver-{suffix}",
        handler=handler,
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=BROKERS,
        max_attempts=1,
        pause_seconds=1.0,
        clock=lambda: clock_now[0],
    )
    await consumer.start()
    try:
        for uri in ("u1", "u2", "u3"):
            await producer.publish(
                topic,
                EventEnvelope[InferenceRequested].new(
                    "inference.requested",
                    InferenceRequested(task=Task.OCR, input_uri=uri),
                ),
                # Ép cùng partition key: mặc định key là trace_id, mỗi message một
                # giá trị khác nhau. Assert về thứ tự chỉ đúng khi cả ba nằm chung
                # một partition — hiện nay đúng nhờ topic tự tạo có 1 partition,
                # tức là đúng do may chứ không do thiết kế.
                key="cung-mot-partition",
            )
        for _ in range(40):
            await consumer.run_once()
            clock_now[0] += 1.0               # cho qua cửa sổ pause
            if len(handled) == 3:
                break
            await asyncio.sleep(0.2)
    finally:
        await consumer.stop()
        await producer.stop()

    assert handled == ["u1", "u2", "u3"], f"mất hoặc đảo thứ tự: {handled}"
    assert len(handled) == len(set(handled)), f"xử lý trùng: {handled}"
