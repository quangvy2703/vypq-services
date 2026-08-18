import asyncio
from collections.abc import Awaitable, Callable

import httpx
from vypq_contracts.common import ErrorCode, Task
from vypq_core.errors import ServiceError
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.http_client import UpstreamError
from vypq_core.logging import get_logger, setup_logging
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceCompleted, InferenceRequested
from vypq_events.topics import dlq_topic, request_topic, result_topic

from __PKG__.backend.remote import Remote__BACKEND__
from __PKG__.handler import __HANDLER__
from __PKG__.settings import __SETTINGS__, load_hosts

log = get_logger(__name__)


def group_id(prefix: str, model_version: str | None) -> str:
    """Không đặt MODEL_VERSION → group mặc định. Có đặt → group riêng cho model đó,
    nên cùng một event được mọi model version đang bật xử lý (shadow-run)."""
    return f"{prefix}-{model_version}" if model_version else f"{prefix}-default"


async def fetch_bytes(uri: str) -> bytes:
    """Tải input, PHÂN LOẠI ĐÚNG lỗi tải.

    httpx trần ném ConnectError/TimeoutException — những lỗi này không phải
    UpstreamError nên EventConsumer coi là dữ liệu hỏng và dead-letter ngay.
    Hậu quả đo được: MinIO/R2 chập chờn vài giây là cả hàng đợi rơi vào DLQ,
    dù chẳng có gì sai với dữ liệu. Kết nối hỏng và 5xx là sự cố hạ tầng →
    UpstreamError → consumer dừng chờ. Chỉ 4xx mới thật sự là URI hỏng.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(uri)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise UpstreamError(f"không tải được {uri}: {exc}") from exc
    if response.status_code >= 500:
        raise UpstreamError(f"{uri} trả {response.status_code}")
    if response.status_code >= 400:
        raise ServiceError(
            ErrorCode.BAD_INPUT, f"{uri} trả {response.status_code}", http_status=422
        )
    return response.content


class __WORKERHANDLER__:
    def __init__(
        self,
        handler: __HANDLER__,
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
            task=Task.__TASKUPPER__,
            model_version=response.model_version,
            input_uri=request.input_uri,
            output=response.result.model_dump(mode="json"),
            latency_ms=response.latency_ms,
            eval_job_id=request.eval_job_id,
            dataset_item_id=request.dataset_item_id,
        )
        await self._producer.publish(
            result_topic(Task.__TASKUPPER__),
            EventEnvelope[InferenceCompleted].new(
                "inference.completed", completed, trace_id=envelope.trace_id
            ),
            key=envelope.trace_id,
        )


async def main() -> None:
    settings = __SETTINGS__()
    setup_logging(settings.log_level)
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = Remote__BACKEND__(registry, timeout_s=settings.timeout_s)
    handler = __HANDLER__(backend, default_model=settings.default_model)
    producer = EventProducer(settings.brokers)
    await producer.start()

    consumer = EventConsumer(
        topic=request_topic(Task.__TASKUPPER__),
        group_id=group_id(settings.group_prefix, settings.model_version),
        handler=__WORKERHANDLER__(handler, producer, forced_model=settings.model_version),
        dlq_topic=dlq_topic(Task.__TASKUPPER__),
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
