import asyncio

import pytest
from vypq_contracts.common import Task
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
