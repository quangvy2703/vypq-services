import asyncio
import functools
from collections.abc import Awaitable, Callable

import httpx
from vypq_contracts.common import ErrorCode, Task
from vypq_core.errors import ServiceError
from vypq_core.fetch import DownloadTooLarge, fetch_capped
from vypq_core.http_client import UpstreamError
from vypq_core.logging import get_logger, setup_logging
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceCompleted, InferenceRequested
from vypq_events.topics import dlq_topic, request_topic, result_topic

from asr_service.backend.remote import RemoteAsrBackend
from asr_service.handler import AsrHandler
from asr_service.settings import AsrSettings, build_host_registry

log = get_logger(__name__)


def group_id(prefix: str, model_version: str | None) -> str:
    """Không đặt MODEL_VERSION → group mặc định. Có đặt → group riêng cho model đó,
    nên cùng một event được mọi model version đang bật xử lý (shadow-run)."""
    return f"{prefix}-{model_version}" if model_version else f"{prefix}-default"


async def fetch_bytes(
    uri: str, *, max_download_mb: int = 100, fetch_deadline_s: float = 60.0
) -> bytes:
    """Tải input, PHÂN LOẠI ĐÚNG lỗi tải.

    httpx trần ném ConnectError/TimeoutException — những lỗi này không phải
    UpstreamError nên EventConsumer coi là dữ liệu hỏng và dead-letter ngay.
    Hậu quả đo được: MinIO/R2 chập chờn vài giây là cả hàng đợi rơi vào DLQ,
    dù chẳng có gì sai với dữ liệu. Kết nối hỏng và 5xx là sự cố hạ tầng →
    UpstreamError → consumer dừng chờ. Chỉ 4xx mới thật sự là URI hỏng.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            status, body = await fetch_capped(
                client, uri,
                max_bytes=max_download_mb * 1024 * 1024,
                deadline_s=fetch_deadline_s,
            )
    except DownloadTooLarge as exc:
        # Dữ liệu hỏng, KHÔNG phải sự cố hạ tầng: một URI quá cỡ thì retry lần
        # nào cũng quá cỡ. Xếp vào UpstreamError sẽ pause và kẹt cả partition.
        raise ServiceError(ErrorCode.BAD_INPUT, str(exc), http_status=413) from exc
    except TimeoutError as exc:
        # Hết deadline tổng: kho đối tượng nhỏ giọt là sự cố hạ tầng, phải chờ
        # chứ không dead-letter.
        raise UpstreamError(f"quá hạn {fetch_deadline_s}s khi tải {uri}") from exc
    except (httpx.UnsupportedProtocol, httpx.InvalidURL) as exc:
        # PHẢI bắt TRƯỚC TransportError: UnsupportedProtocol kế thừa từ nó.
        # URI sai scheme hay sai định dạng thì thử lại bao nhiêu lần cũng hỏng
        # y hệt — xếp vào hạ tầng sẽ làm consumer pause vô hạn và kẹt cả
        # partition sau một URI hỏng, trong khi DLQ vẫn rỗng.
        raise ServiceError(
            ErrorCode.BAD_INPUT, f"URI không dùng được: {uri} ({exc})", http_status=422
        ) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise UpstreamError(f"không tải được {uri}: {exc}") from exc
    if status >= 500:
        raise UpstreamError(f"{uri} trả {status}")
    if status >= 400:
        raise ServiceError(ErrorCode.BAD_INPUT, f"{uri} trả {status}", http_status=422)
    return body


class AsrWorkerHandler:
    def __init__(
        self,
        handler: AsrHandler,
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
            task=Task.ASR,
            model_version=response.model_version,
            input_uri=request.input_uri,
            output=response.result.model_dump(mode="json"),
            latency_ms=response.latency_ms,
            eval_job_id=request.eval_job_id,
            dataset_item_id=request.dataset_item_id,
        )
        await self._producer.publish(
            result_topic(Task.ASR),
            EventEnvelope[InferenceCompleted].new(
                "inference.completed", completed, trace_id=envelope.trace_id
            ),
            key=envelope.trace_id,
        )


async def main() -> None:
    settings = AsrSettings()
    setup_logging(settings.log_level)
    registry = build_host_registry(settings)
    backend = RemoteAsrBackend(registry, timeout_s=settings.timeout_s)
    handler = AsrHandler(backend, default_model=settings.default_model)
    producer = EventProducer(settings.brokers)
    await producer.start()

    consumer = EventConsumer(
        topic=request_topic(Task.ASR),
        group_id=group_id(settings.group_prefix, settings.model_version),
        handler=AsrWorkerHandler(
            handler, producer, forced_model=settings.model_version,
            fetch=functools.partial(
                fetch_bytes,
                max_download_mb=settings.max_download_mb,
                fetch_deadline_s=settings.fetch_deadline_s,
            ),
        ),
        dlq_topic=dlq_topic(Task.ASR),
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
        # worker.py là tiến trình chạy dài: không đóng thì client httpx bên
        # trong DiscoveryHostRegistry rò tài nguyên suốt vòng đời tiến trình.
        await registry.aclose()


if __name__ == "__main__":
    asyncio.run(main())
