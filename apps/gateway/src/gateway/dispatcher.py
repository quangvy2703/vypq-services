from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import InvokeRequest
from vypq_core.errors import ServiceError
from vypq_events.envelope import EventEnvelope
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import request_topic

from gateway.registry.services import ServiceRegistry


class Dispatcher:
    """Đẩy request vào Kafka cho worker xử lý.

    KHÔNG tạo dòng `runs` ở đây: shadow-run cho nhiều model version cùng xử lý
    một event, nên chưa biết sẽ có bao nhiêu kết quả và mỗi cái thuộc model nào.
    Result consumer ghi khi kết quả thực sự về.
    """

    def __init__(self, registry: ServiceRegistry, producer) -> None:
        self._registry = registry
        self._producer = producer

    async def dispatch(self, request: InvokeRequest, trace_id: str) -> None:
        state = self._registry.get(request.service)
        if state is None:
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"không có service '{request.service}'", 404
            )
        if state.info is None:
            # KHÔNG đoán task. Topic chọn theo task; đoán sai là đẩy việc sang
            # hàng đợi của service khác, im lặng, trong khi người gọi đã cầm
            # trace_id và tin rằng việc đã được nhận.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"gateway chưa liên hệ được '{request.service}' lần nào, chưa biết task",
                503,
            )
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "đường async cần input_uri", 422)

        # Không kiểm status: khác đường sync, message nằm trong topic chờ service
        # sống lại. Từ chối ở đây là vứt việc đi vì một sự cố tạm thời.
        payload = InferenceRequested(
            task=state.info.task,
            input_uri=request.input_uri,
            model_version=request.model_version,
        )
        envelope = EventEnvelope[InferenceRequested].new(
            "inference.requested", payload, trace_id=trace_id
        )
        await self._producer.publish(
            request_topic(state.info.task), envelope, key=trace_id
        )
