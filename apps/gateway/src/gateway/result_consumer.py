from collections.abc import Callable

from vypq_contracts.common import Task
from vypq_contracts.gateway import InvokeMode, RunStatus
from vypq_core.http_client import UpstreamError
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
        try:
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
        except Exception as exc:
            # Từng bọc mỗi SQLAlchemyError — vẫn lọt OSError khi Postgres chết
            # hẳn (container restart, network partition, DNS lỗi): asyncpg thất
            # bại ngay ở connect(), TRƯỚC KHI có kết nối DBAPI để SQLAlchemy bọc
            # lại thành SQLAlchemyError. Đây là lần thứ năm một kiểu exception
            # hạ tầng lọt qua allowlist kiểu exception trên nhánh này — liệt kê
            # từng loại là trò chơi không bao giờ thắng được. Đảo lại quy tắc:
            # trong handler này, đúng MỘT lỗi là dữ liệu hỏng — model_validate ở
            # trên thất bại — nên nó nằm NGOÀI khối try này và được ném thẳng ra
            # để dead-letter. Mọi lỗi của khối ghi DB, bất kể hình dạng gì
            # (OperationalError, OSError, hay bất cứ thứ gì asyncpg/SQLAlchemy
            # tương lai còn ném ra), đều là hạ tầng: DB chập chờn khi ghi một
            # KẾT QUẢ INFERENCE ĐÃ CHẠY XONG (GPU đã tốn thời gian, kết quả đã
            # có) không bao giờ là lỗi dữ liệu. Bọc thành UpstreamError để
            # consumer dừng chờ DB quay lại thay vì mất kết quả.
            raise UpstreamError(f"không ghi được run vào DB: {exc}") from exc

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
                # Trả KHOÁ ĐỊNH TUYẾN chứ không phải tên service tự khai: đường
                # sync ghi runs.service bằng khoá đó (SyncProxy.invoke), nên trả
                # info.name ở đây sẽ làm hai đường ghi hai giá trị khác nhau cho
                # cùng một service, và lọc theo service ở /v1/runs mất một nửa.
                return state.name
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
