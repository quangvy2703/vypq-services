from collections.abc import Callable

from vypq_contracts.common import Task
from vypq_contracts.gateway import InvokeMode, RunStatus
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import RawEnvelope
from vypq_events.schemas.inference import InferenceCompleted
from vypq_events.topics import dlq_topic, result_topic

from gateway.db.repo import RunRepo
from gateway.settings import GatewaySettings


def make_result_handler(session_factory, service_name_for: Callable[[Task], str]):
    async def handle(envelope: RawEnvelope) -> None:
        # Không bọc try: envelope hỏng là dữ liệu hỏng, phải ném để
        # EventConsumer đẩy vào DLQ. Nuốt ở đây là mất kết quả mà không ai biết.
        completed = InferenceCompleted.model_validate(envelope.payload)
        async with session_factory() as session:
            await RunRepo(session).record(
                trace_id=envelope.trace_id,
                service=service_name_for(completed.task),
                model_version=completed.model_version,
                mode=InvokeMode.ASYNC,
                status=RunStatus.OK,
                input_uri=completed.input_uri,
                output=completed.output,
                latency_ms=completed.latency_ms,
                error=None,
            )

    return handle


def build_result_consumers(
    session_factory, settings: GatewaySettings, producer, registry
) -> list[EventConsumer]:
    def service_name_for(task: Task) -> str:
        for state in registry.states():
            # info=None nghĩa là gateway CHƯA TỪNG poll thành công service đó
            # (xem ServiceState.info). Đọc thẳng state.info.task ở đây ném
            # AttributeError — không phải lỗi hạ tầng theo default_is_retryable
            # — nên EventConsumer sẽ dead-letter một kết quả inference hoàn
            # toàn lành. Bỏ qua những state chưa biết info thay vì đoán.
            if state.info is not None and state.info.task is task:
                return state.info.name
        return task.value

    handler = make_result_handler(session_factory, service_name_for)
    return [
        EventConsumer(
            topic=result_topic(task),
            group_id="gateway-results",
            handler=handler,
            dlq_topic=dlq_topic(task),
            producer=producer,
            brokers=settings.brokers,
        )
        for task in (Task.OCR, Task.ASR)
    ]
