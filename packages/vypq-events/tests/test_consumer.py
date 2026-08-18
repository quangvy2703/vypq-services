from dataclasses import dataclass, field

import pytest
from vypq_contracts.common import Task
from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import NoHostAvailableError
from vypq_core.http_client import UpstreamError
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested

# Không dùng conftest.py: --import-mode=importlib khiến `from conftest import ...`
# hỏng, nên các fake Kafka này được đặt ngay trong file test dùng chúng.


@dataclass(frozen=True)
class TP:
    topic: str
    partition: int = 0


@dataclass
class FakeMessage:
    value: bytes
    offset: int
    topic: str = "infer.ocr.requests"
    partition: int = 0
    key: bytes | None = None


@dataclass
class FakeConsumer:
    """Thay aiokafka.AIOKafkaConsumer trong unit test."""

    batches: list[dict] = field(default_factory=list)
    committed: int = 0
    paused_tps: set = field(default_factory=set)
    seeks: list[tuple] = field(default_factory=list)
    _tp: TP = field(default_factory=lambda: TP("infer.ocr.requests", 0))

    async def getmany(self, timeout_ms: int = 1000, max_records: int | None = None):
        # Consumer thật trả rỗng cho partition đang pause. Fake phải giống, nếu
        # không test sẽ thấy message vẫn chảy vào lúc đang dừng, và ta sẽ đi sửa
        # nhầm production code cho khớp một cái fake sai.
        if self.paused_tps or not self.batches:
            return {}
        return self.batches.pop(0)

    def assignment(self):
        return {self._tp}

    def paused(self):
        return set(self.paused_tps)

    def pause(self, *tps):
        self.paused_tps.update(tps)

    def resume(self, *tps):
        self.paused_tps.difference_update(tps)

    def seek(self, tp, offset):
        self.seeks.append((tp, offset))

    async def commit(self):
        self.committed += 1


@dataclass
class FakeProducer:
    published: list[tuple] = field(default_factory=list)

    async def publish(self, topic, envelope, key=None):
        self.published.append((topic, envelope, key))


TOPIC_TP = TP("infer.ocr.requests", 0)


def _msg(offset: int, uri: str = "s3://b/a.jpg") -> FakeMessage:
    env = EventEnvelope[InferenceRequested].new(
        "inference.requested", InferenceRequested(task=Task.OCR, input_uri=uri)
    )
    return FakeMessage(value=env.model_dump_json().encode(), offset=offset)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


async def _noop_sleep(_s: float) -> None:
    return None


def _consumer(kafka, producer, handler, clock=None, **kw) -> EventConsumer:
    return EventConsumer(
        topic="infer.ocr.requests",
        group_id="ocr-default",
        handler=handler,
        dlq_topic="infer.ocr.dlq",
        producer=producer,
        consumer=kafka,
        sleep=_noop_sleep,
        clock=clock or Clock(),
        max_attempts=kw.pop("max_attempts", 3),
        pause_seconds=kw.pop("pause_seconds", 10.0),
        **kw,
    )


async def test_processes_batch_and_commits():
    seen = []

    async def handler(env):
        seen.append(env)

    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0), _msg(1)]}])
    c = _consumer(kafka, FakeProducer(), handler)
    processed = await c.run_once()
    assert processed == 2
    assert len(seen) == 2
    assert kafka.committed == 1


async def test_permanent_error_goes_to_dlq_and_processing_continues():
    calls = []

    async def handler(env):
        calls.append(env)
        if len(calls) == 1:
            raise ValueError("ảnh hỏng")

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0), _msg(1)]}])
    c = _consumer(kafka, producer, handler)
    processed = await c.run_once()
    assert processed == 2
    assert len(producer.published) == 1
    assert producer.published[0][0] == "infer.ocr.dlq"
    assert kafka.seeks == []


@pytest.mark.parametrize(
    "exc",
    [
        CircuitOpenError("gpu"),
        UpstreamError("gpu chết"),
        # Chưa đăng ký máy thuê, hoặc máy vừa tắt — hạ tầng, không phải dữ liệu.
        NoHostAvailableError("m1"),
    ],
)
async def test_retryable_exhaustion_pauses_and_seeks_back_without_dlq(exc):
    async def handler(_env):
        raise exc

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(5), _msg(6)]}])
    c = _consumer(kafka, producer, handler, max_attempts=2)
    processed = await c.run_once()

    assert processed == 0
    assert producer.published == []          # tuyệt đối không đẩy vào DLQ
    assert kafka.seeks == [(TOPIC_TP, 5)]    # tua về đúng message đang dở
    assert TOPIC_TP in kafka.paused_tps      # đã dừng consume
    assert kafka.committed == 1              # commit tới trước message đó


async def test_retryable_then_success_does_not_pause():
    attempts = []

    async def handler(_env):
        attempts.append(1)
        if len(attempts) == 1:
            raise UpstreamError("chập chờn")

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}])
    c = _consumer(kafka, producer, handler, max_attempts=3)
    processed = await c.run_once()
    assert processed == 1
    assert len(attempts) == 2
    assert kafka.paused_tps == set()
    assert producer.published == []


async def test_malformed_json_goes_to_dlq():
    async def handler(_env):
        raise AssertionError("không bao giờ được gọi")

    producer = FakeProducer()
    bad = FakeMessage(value=b"{khong-phai-json", offset=0)
    kafka = FakeConsumer(batches=[{TOPIC_TP: [bad]}])
    c = _consumer(kafka, producer, handler)
    processed = await c.run_once()
    assert processed == 1
    assert producer.published[0][0] == "infer.ocr.dlq"


async def test_pause_rewinds_every_partition_in_the_batch():
    # commit() không tham số commit vị trí của MỌI partition được gán. Partition
    # nào đã được getmany() trả record mà vòng lặp chưa chạy tới sẽ bị commit qua
    # và mất record vĩnh viễn. Test 1 partition không bao giờ thấy lỗi này.
    tp_a = TP("infer.ocr.requests", 0)
    tp_b = TP("infer.ocr.requests", 1)

    async def handler(_env):
        raise UpstreamError("gpu chết")

    kafka = FakeConsumer(batches=[{tp_a: [_msg(10)], tp_b: [_msg(20), _msg(21)]}])
    c = _consumer(kafka, FakeProducer(), handler, max_attempts=1)
    await c.run_once()

    # Cả hai partition phải được tua về record chưa xử lý đầu tiên của chính nó.
    assert dict(kafka.seeks) == {tp_a: 10, tp_b: 20}


async def test_dlq_publish_failure_pauses_instead_of_killing_the_consumer():
    class BrokenProducer(FakeProducer):
        async def publish(self, topic, envelope, key=None):
            raise RuntimeError("broker chết")

    async def handler(_env):
        raise ValueError("dữ liệu hỏng")      # lỗi vĩnh viễn → đáng lẽ vào DLQ

    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(7)]}])
    c = _consumer(kafka, BrokenProducer(), handler, max_attempts=1)

    processed = await c.run_once()            # không được ném ra ngoài
    assert processed == 0
    assert kafka.seeks == [(TOPIC_TP, 7)]     # giữ nguyên message, không bỏ qua
    assert TOPIC_TP in kafka.paused_tps


async def test_pause_stops_fetching_then_resumes_and_carries_on():
    gpu_down = [True]

    async def handler(_env):
        if gpu_down[0]:
            raise UpstreamError("gpu chết")

    clock = Clock()
    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}, {TOPIC_TP: [_msg(1)]}])
    c = _consumer(kafka, producer, handler, clock=clock, max_attempts=1, pause_seconds=10.0)

    await c.run_once()
    assert TOPIC_TP in kafka.paused_tps
    assert len(kafka.batches) == 1            # batch sau chưa bị đụng tới

    clock.advance(5.0)
    await c.run_once()
    assert TOPIC_TP in kafka.paused_tps       # chưa hết cửa sổ chờ, vẫn dừng
    assert len(kafka.batches) == 1            # và tuyệt đối không lấy thêm gì

    gpu_down[0] = False
    clock.advance(6.0)
    processed = await c.run_once()
    assert kafka.paused_tps == set()          # hết cửa sổ → resume
    assert processed == 1                     # và tiêu thụ tiếp được
    assert producer.published == []           # suốt quá trình không DLQ cái nào


async def test_poison_message_is_dead_lettered_after_pause_limit_then_progress_resumes():
    # input_uri trỏ tới host đã biến mất vĩnh viễn: handler luôn lỗi retryable cho
    # đúng message này; mọi message khác (không trùng uri) xử lý bình thường.
    dead_host = "s3://dead-host/permanently-gone.jpg"

    async def handler(env):
        if env.payload["input_uri"] == dead_host:
            raise UpstreamError("host đã biến mất vĩnh viễn")

    clock = Clock()
    producer = FakeProducer()
    poison_rounds = [{TOPIC_TP: [_msg(0, uri=dead_host)]} for _ in range(4)]
    kafka = FakeConsumer(batches=poison_rounds + [{TOPIC_TP: [_msg(1)]}])
    c = _consumer(
        kafka,
        producer,
        handler,
        clock=clock,
        max_attempts=1,
        pause_seconds=10.0,
        max_pause_rounds=3,
    )

    for _ in range(4):
        await c.run_once()
        clock.advance(11.0)

    assert len(producer.published) == 1
    assert producer.published[0][0] == "infer.ocr.dlq"
    assert kafka.paused_tps == set()          # không còn treo ở message này nữa

    processed = await c.run_once()            # batch kế tiếp trong hàng đợi
    assert processed == 1                     # được xử lý bình thường, không bị chặn
    assert len(producer.published) == 1       # không có DLQ nào phát sinh thêm


async def test_pause_round_counter_resets_when_head_offset_changes():
    # offset 0 lỗi 2 lần rồi thành công; offset 1 lỗi 2 lần sau đó. Nếu bộ đếm
    # không reset theo offset đang đứng đầu, hai lần lỗi của offset 1 sẽ cộng dồn
    # lên hai lần lỗi trước đó của offset 0 và có thể vượt ngưỡng oan.
    uri_a, uri_b = "s3://gpu-a/img.jpg", "s3://gpu-b/img.jpg"
    attempts_a = [0]

    async def handler(env):
        uri = env.payload["input_uri"]
        if uri == uri_a:
            if attempts_a[0] < 2:
                attempts_a[0] += 1
                raise UpstreamError("gpu-a chập chờn")
            return
        if uri == uri_b:
            raise UpstreamError("gpu-b chập chờn")

    clock = Clock()
    producer = FakeProducer()
    kafka = FakeConsumer(
        batches=[
            {TOPIC_TP: [_msg(0, uri=uri_a)]},
            {TOPIC_TP: [_msg(0, uri=uri_a)]},
            {TOPIC_TP: [_msg(0, uri=uri_a)]},  # lần thứ 3 mới thành công
            {TOPIC_TP: [_msg(1, uri=uri_b)]},
            {TOPIC_TP: [_msg(1, uri=uri_b)]},
        ]
    )
    c = _consumer(
        kafka,
        producer,
        handler,
        clock=clock,
        max_attempts=1,
        pause_seconds=10.0,
        max_pause_rounds=3,
    )

    for _ in range(5):
        await c.run_once()
        clock.advance(11.0)

    assert producer.published == []           # không message nào bị dead-letter


async def test_default_pause_rounds_rides_out_a_handful_of_rounds_without_dlq():
    # Sự cố hạ tầng bình thường (vài vòng pause) không được phép làm rơi message
    # vào DLQ — đây chính là hành vi "lossless" mà cơ chế pause tồn tại để giữ.
    async def handler(_env):
        raise UpstreamError("outage hạ tầng kéo dài nhưng chưa vượt ngưỡng")

    clock = Clock()
    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]} for _ in range(5)])
    c = _consumer(
        kafka,
        producer,
        handler,
        clock=clock,
        max_attempts=1,
        pause_seconds=30.0,
        max_pause_rounds=40,
    )

    for _ in range(5):
        await c.run_once()
        clock.advance(31.0)

    assert producer.published == []            # vẫn lossless, chưa gần tới ngưỡng
    assert TOPIC_TP in kafka.paused_tps         # vẫn đang chờ hạ tầng, không bỏ cuộc


async def test_producer_wraps_broker_failure_as_upstream_error():
    # Broker trục trặc lúc publish kết quả không được coi là dữ liệu hỏng:
    # inference đã chạy xong rồi, dead-letter là vứt mất kết quả đã trả tiền.
    class BrokenKafka:
        async def send_and_wait(self, *_args, **_kwargs):
            raise RuntimeError("broker mat ket noi")

    producer = EventProducer(producer=BrokenKafka())
    env = EventEnvelope[InferenceRequested].new(
        "inference.requested", InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg")
    )
    with pytest.raises(UpstreamError):
        await producer.publish("infer.ocr.results", env)
