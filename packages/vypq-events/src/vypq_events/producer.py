from aiokafka import AIOKafkaProducer

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
        await self._producer.send_and_wait(
            topic, envelope.model_dump_json().encode(), key=partition_key
        )
