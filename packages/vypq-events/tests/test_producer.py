from dataclasses import dataclass, field

import pytest
from vypq_contracts.common import Task
from vypq_core.http_client import UpstreamError
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested

# Không dùng conftest.py: --import-mode=importlib khiến `from conftest import ...`
# hỏng (xem test_consumer.py), nên fake Kafka nằm ngay trong file dùng nó.


@dataclass
class FakeKafkaProducer:
    """Thay aiokafka.AIOKafkaProducer trong unit test."""

    started: int = 0
    stopped: int = 0
    sent: list[tuple] = field(default_factory=list)

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    async def send_and_wait(self, topic, value, key=None):
        self.sent.append((topic, value, key))


def _envelope() -> EventEnvelope[InferenceRequested]:
    return EventEnvelope[InferenceRequested].new(
        "inference.requested", InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg")
    )


async def test_stop_without_start_is_a_safe_noop():
    # __init__ hoãn dựng producer thật (xem lời giải thích trong producer.py);
    # nếu chưa từng start(), self._producer vẫn là None và stop() không có gì
    # để dừng. Không được ném AttributeError khi gọi .stop() trên None.
    producer = EventProducer()
    await producer.stop()  # không được ném


async def test_publish_before_start_raises_a_clear_error_not_attributeerror():
    producer = EventProducer()
    with pytest.raises(UpstreamError, match="chưa start"):
        await producer.publish("infer.ocr.results", _envelope())


async def test_start_twice_does_not_build_a_second_underlying_producer(monkeypatch):
    # Không truyền `producer=` ở đây: ta muốn thử đúng nhánh dựng-hoãn (lúc
    # self._producer vẫn None), tức là cách start() thật sự được gọi ở
    # composition root. Vá AIOKafkaProducer trong module producer bằng một
    # factory đếm số lần dựng, để không cần broker thật.
    built = []

    def fake_factory(*_args, **_kwargs):
        instance = FakeKafkaProducer()
        built.append(instance)
        return instance

    monkeypatch.setattr("vypq_events.producer.AIOKafkaProducer", fake_factory)

    producer = EventProducer()
    await producer.start()
    await producer.start()

    # Nếu start() không guard bằng `if self._producer is None`, lần start() thứ
    # hai sẽ dựng một AIOKafkaProducer MỚI đè lên cái đầu, mất hết state (offset
    # buffer, kết nối) của cái cũ.
    assert len(built) == 1
    first = built[0]
    assert producer._producer is first
    assert first.started == 2

    await producer.publish("infer.ocr.results", _envelope())
    assert len(first.sent) == 1
