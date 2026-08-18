import asyncio
import subprocess
import time

import pytest
from vypq_contracts.common import Task
from vypq_core.http_client import UpstreamError
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import dlq_topic

pytestmark = pytest.mark.slow
BROKERS = "localhost:9092"


async def test_roundtrip_through_real_redpanda():
    # Topic và group phải là DUY NHẤT mỗi lần chạy. Dùng topic dùng chung thì test
    # nuốt luôn message của lần chạy trước (hoặc của người khác đang thử tay) và
    # fail ngẫu nhiên — "xanh khi môi trường sạch" là loại test tệ hơn không có.
    suffix = str(int(time.time() * 1000))
    topic = f"infer.ocr.requests.roundtrip.{suffix}"
    producer = EventProducer(BROKERS)
    await producer.start()
    received: list = []

    async def handler(env):
        received.append(env)

    consumer = EventConsumer(
        topic=topic,
        group_id=f"test-roundtrip-{suffix}",
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
        await producer.publish(topic, env)
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


async def test_pause_on_multi_partition_topic_loses_nothing():
    """Chỉ topic THẬT nhiều partition mới bắt được lỗi "chỉ tua một partition".

    test_pause_rewinds_every_partition_in_the_batch (unit, FakeConsumer) chỉ
    chứng minh seek() được gọi đúng cho từng partition — nó không chứng minh
    Kafka thật sự giao lại record sau đó. Hai test integration còn lại trong
    file này đều chạy trên topic 1 partition nên không bao giờ để lộ bug: với
    1 partition thì "tua một partition" và "tua mọi partition" là cùng một
    hành động. Test này tạo topic 3 partition thật, rải 9 message ra các
    partition bằng key khác nhau, cho handler chết ở message đầu tiên nó thấy,
    rồi lái run_once() qua chu kỳ pause → resume tới khi im lặng.
    """
    suffix = str(int(time.time() * 1000))
    topic = f"infer.ocr.requests.multipart.{suffix}"
    group = f"test-multipart-{suffix}"

    subprocess.run(
        ["docker", "exec", "compose-redpanda-1", "rpk", "topic", "create", topic, "-p", "3"],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        describe = subprocess.run(
            ["docker", "exec", "compose-redpanda-1", "rpk", "topic", "describe", topic],
            check=True,
            capture_output=True,
            text=True,
        )
        partitions_line = next(
            line for line in describe.stdout.splitlines() if line.startswith("PARTITIONS")
        )
        assert partitions_line.split()[-1] == "3", (
            f"topic không thật sự có 3 partition: {describe.stdout}"
        )

        producer = EventProducer(BROKERS)
        await producer.start()

        uris = [f"multipart-u{i}" for i in range(9)]
        handled: list[str] = []
        first_seen: list[str] = []

        async def handler(env):
            uri = env.payload["input_uri"]
            if not first_seen:
                first_seen.append(uri)
                raise UpstreamError("gpu chết ở message đầu tiên thấy được")
            handled.append(uri)

        clock_now = [0.0]
        consumer = EventConsumer(
            topic=topic,
            group_id=group,
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
            for uri in uris:
                await producer.publish(
                    topic,
                    EventEnvelope[InferenceRequested].new(
                        "inference.requested",
                        InferenceRequested(task=Task.OCR, input_uri=uri),
                    ),
                    # Key khác nhau để 9 message rải ra cả 3 partition thay vì
                    # dồn vào một, điều mà hai test integration kia không làm.
                    key=uri,
                )
            for _ in range(60):
                await consumer.run_once()
                clock_now[0] += 1.0  # cho qua cửa sổ pause
                if len(handled) == len(uris):
                    break
                await asyncio.sleep(0.2)
        finally:
            await consumer.stop()
            await producer.stop()

        assert sorted(handled) == sorted(uris), (
            f"mất message: thiếu {sorted(set(uris) - set(handled))}, handled={sorted(handled)}"
        )
        assert len(handled) == len(set(handled)), f"xử lý trùng: {handled}"
    finally:
        subprocess.run(
            ["docker", "exec", "compose-redpanda-1", "rpk", "topic", "delete", topic],
            capture_output=True,
            text=True,
        )
