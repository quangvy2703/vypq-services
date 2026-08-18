from aiokafka import AIOKafkaProducer
from vypq_core.http_client import UpstreamError

from vypq_events.envelope import EventEnvelope


class EventProducer:
    def __init__(self, brokers: str = "localhost:9092", producer=None) -> None:
        self._producer = producer or AIOKafkaProducer(bootstrap_servers=brokers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        # Partition key mặc định là trace_id → mọi event của một request cùng partition.
        partition_key = (key or envelope.trace_id).encode()
        try:
            await self._producer.send_and_wait(
                topic, envelope.model_dump_json().encode(), key=partition_key
            )
        except Exception as exc:
            # aiokafka ném exception riêng của nó, không phải UpstreamError. Không
            # bọc lại thì consumer coi là dữ liệu hỏng và dead-letter — mất luôn
            # kết quả inference ĐÃ CHẠY XONG, tức là vứt đi thời gian GPU đã trả tiền.
            raise UpstreamError(f"không publish được vào {topic}: {exc}") from exc
