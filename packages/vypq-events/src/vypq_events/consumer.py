import asyncio
import time
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer
from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import NoHostAvailableError
from vypq_core.http_client import UpstreamError
from vypq_core.logging import get_logger, set_trace_id

from vypq_events.envelope import EventEnvelope, RawEnvelope

log = get_logger(__name__)

Handler = Callable[[RawEnvelope], Awaitable[None]]


def default_is_retryable(exc: Exception) -> bool:
    """Lỗi của upstream thì đáng chờ; lỗi của dữ liệu thì không.

    NoHostAvailableError nằm ở đây vì "chưa có host khoẻ nào" là tình trạng hạ
    tầng, không phải dữ liệu hỏng: máy GPU thuê chưa đăng ký xong, hoặc vừa hết
    giờ và tắt. Xếp nhầm nó vào nhóm dữ liệu hỏng thì cả hàng đợi rơi vào DLQ
    đúng lúc không có máy nào chạy — chính thảm hoạ mà cơ chế pause sinh ra để ngăn.
    """
    return isinstance(exc, (CircuitOpenError, UpstreamError, NoHostAvailableError))


class _PauseSignal(Exception):
    """Nội bộ: báo run_once dừng consume thay vì đẩy message vào DLQ."""


class EventConsumer:
    def __init__(
        self,
        *,
        topic: str,
        group_id: str,
        handler: Handler,
        dlq_topic: str,
        producer,
        brokers: str = "localhost:9092",
        consumer=None,
        max_attempts: int = 3,
        base_delay_s: float = 0.5,
        pause_seconds: float = 30.0,
        poll_ms: int = 1000,
        max_records: int = 20,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        is_retryable: Callable[[Exception], bool] = default_is_retryable,
    ) -> None:
        self._handler = handler
        self._dlq_topic = dlq_topic
        self._producer = producer
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._pause_seconds = pause_seconds
        self._poll_ms = poll_ms
        self._max_records = max_records
        self._sleep = sleep
        self._clock = clock
        self._is_retryable = is_retryable
        self._paused_until: float | None = None
        self._consumer = consumer or AIOKafkaConsumer(
            topic,
            bootstrap_servers=brokers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def run(self) -> None:
        while True:
            await self.run_once()

    async def run_once(self) -> int:
        # Vẫn gọi getmany() khi đang pause, không bỏ qua: consumer thật trả rỗng
        # sau timeout_ms nên vòng lặp tự có nhịp, và aiokafka giữ được heartbeat
        # với group. Bỏ poll đi thì run() quay tít không nghỉ.
        self._maybe_resume()
        batch = await self._consumer.getmany(
            timeout_ms=self._poll_ms, max_records=self._max_records
        )
        processed = 0
        for tp, messages in batch.items():
            for message in messages:
                try:
                    await self._process(message)
                except _PauseSignal:
                    # Tua về đúng message đang dở rồi commit: mọi thứ trước nó
                    # coi như xong, còn nó sẽ được giao lại khi resume.
                    self._consumer.seek(tp, message.offset)
                    await self._consumer.commit()
                    self._pause()
                    return processed
                processed += 1
        if processed:
            await self._consumer.commit()
        return processed

    def _pause(self) -> None:
        assignment = self._consumer.assignment()
        if assignment:
            self._consumer.pause(*assignment)
        self._paused_until = self._clock() + self._pause_seconds
        log.warning("consumer_paused", seconds=self._pause_seconds)

    def _maybe_resume(self) -> None:
        if self._paused_until is None:
            return
        if self._clock() < self._paused_until:
            return
        paused = self._consumer.paused()
        if paused:
            self._consumer.resume(*paused)
        self._paused_until = None
        log.info("consumer_resumed")

    async def _process(self, message) -> None:
        try:
            envelope = RawEnvelope.model_validate_json(message.value)
        except Exception as exc:
            log.error("envelope_parse_failed", error=str(exc))
            await self._to_dlq(message, None, exc, attempts=1)
            return

        set_trace_id(envelope.trace_id)
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._handler(envelope)
                return
            except Exception as exc:
                if not self._is_retryable(exc):
                    await self._to_dlq(message, envelope, exc, attempts=attempt)
                    return
                if attempt == self._max_attempts:
                    log.warning("retry_exhausted_pausing", error=str(exc))
                    raise _PauseSignal from exc
                await self._sleep(self._base_delay * (2 ** (attempt - 1)))

    async def _to_dlq(self, message, envelope, exc: Exception, attempts: int) -> None:
        dead = EventEnvelope[RawEnvelope].new(
            "event.dead_lettered",
            RawEnvelope(
                event_id=getattr(envelope, "event_id", "unknown"),
                event_type=getattr(envelope, "event_type", "unknown"),
                trace_id=getattr(envelope, "trace_id", "unknown"),
                occurred_at=getattr(envelope, "occurred_at", None) or _now(),
                payload={
                    "reason": f"{type(exc).__name__}: {exc}",
                    "attempts": attempts,
                    "raw": message.value.decode("utf-8", errors="replace"),
                },
            ),
        )
        try:
            await self._producer.publish(self._dlq_topic, dead)
        except Exception as dlq_exc:
            # Không ghi được vào DLQ thì tuyệt đối không commit qua message này.
            # Broker đang có vấn đề → coi như sự cố hạ tầng và dừng consume, giống
            # hệt lúc upstream chết. Để exception bay tiếp thì nó không phải
            # _PauseSignal, run_once() không bắt, và cả consumer chết đứng.
            log.error("dlq_publish_failed", topic=self._dlq_topic, error=str(dlq_exc))
            raise _PauseSignal from dlq_exc
        log.error("event_dead_lettered", topic=self._dlq_topic, reason=str(exc))


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
