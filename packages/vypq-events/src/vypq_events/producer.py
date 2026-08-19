from aiokafka import AIOKafkaProducer
from vypq_core.http_client import UpstreamError

from vypq_events.envelope import EventEnvelope


class EventProducer:
    def __init__(self, brokers: str = "localhost:9092", producer=None) -> None:
        # KHÔNG dựng AIOKafkaProducer() ở đây: nó đòi asyncio.get_running_loop()
        # ngay lúc __init__ chạy (aiokafka.util.get_running_loop ném RuntimeError
        # nếu không có loop đang chạy). EventProducer thường được dựng ở
        # composition root — vd gateway.main.create_gateway() — lúc MODULE ĐƯỢC
        # IMPORT, tức là TRƯỚC KHI uvicorn/asyncio.run tạo loop. Hoãn việc dựng
        # object mạng thật sang start(), nơi luôn nằm trong một coroutine với
        # loop đang chạy, để composition root vẫn ở lại là hàm đồng bộ.
        self._brokers = brokers
        self._producer = producer

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(bootstrap_servers=self._brokers)
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        if self._producer is None:
            raise UpstreamError("EventProducer chưa start(), chưa có gì để publish vào")
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
