import asyncio
from collections.abc import Awaitable, Callable

import httpx
from vypq_contracts.common import Task
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.logging import get_logger, setup_logging
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceCompleted, InferenceRequested
from vypq_events.topics import dlq_topic, request_topic, result_topic

from ocr_service.backend.remote import RemoteOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.settings import OcrSettings, load_hosts

log = get_logger(__name__)


def group_id(prefix: str, model_version: str | None) -> str:
    """Không đặt MODEL_VERSION → group mặc định. Có đặt → group riêng cho model đó,
    nên cùng một event được mọi model version đang bật xử lý (shadow-run)."""
    return f"{prefix}-{model_version}" if model_version else f"{prefix}-default"


async def fetch_bytes(uri: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(uri)
    response.raise_for_status()
    return response.content


class OcrWorkerHandler:
    def __init__(
        self,
        handler: OcrHandler,
        producer,
        *,
        forced_model: str | None,
        fetch: Callable[[str], Awaitable[bytes]] = fetch_bytes,
    ) -> None:
        self._handler = handler
        self._producer = producer
        self._forced_model = forced_model
        self._fetch = fetch

    async def __call__(self, envelope: RawEnvelope) -> None:
        request = InferenceRequested.model_validate(envelope.payload)
        image = await self._fetch(request.input_uri)
        # Lỗi upstream ở đây cố ý bay lên EventConsumer để nó pause thay vì DLQ.
        response = await self._handler.run(
            image,
            self._forced_model or request.model_version,
            envelope.trace_id,
        )
        completed = InferenceCompleted(
            task=Task.OCR,
            model_version=response.model_version,
            input_uri=request.input_uri,
            output=response.result.model_dump(mode="json"),
            latency_ms=response.latency_ms,
            eval_job_id=request.eval_job_id,
            dataset_item_id=request.dataset_item_id,
        )
        await self._producer.publish(
            result_topic(Task.OCR),
            EventEnvelope[InferenceCompleted].new(
                "inference.completed", completed, trace_id=envelope.trace_id
            ),
            key=envelope.trace_id,
        )


async def main() -> None:
    settings = OcrSettings()
    setup_logging(settings.log_level)
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = RemoteOcrBackend(registry, timeout_s=settings.timeout_s)
    handler = OcrHandler(
        backend, default_model=settings.default_model, max_side=settings.max_side
    )
    producer = EventProducer(settings.brokers)
    await producer.start()

    consumer = EventConsumer(
        topic=request_topic(Task.OCR),
        group_id=group_id(settings.group_prefix, settings.model_version),
        handler=OcrWorkerHandler(handler, producer, forced_model=settings.model_version),
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=settings.brokers,
    )
    await consumer.start()
    log.info("worker_started", group=group_id(settings.group_prefix, settings.model_version))
    try:
        await consumer.run()
    finally:
        await consumer.stop()
        await producer.stop()
        await backend.aclose()


if __name__ == "__main__":
    asyncio.run(main())
