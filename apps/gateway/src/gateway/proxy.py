import time
import uuid

import httpx
from vypq_contracts.common import ErrorCode, HealthStatus
from vypq_contracts.gateway import InvokeMode, RunRecord, RunStatus
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

from gateway.db.repo import RunRepo
from gateway.registry.services import ServiceRegistry

log = get_logger(__name__)


class SyncProxy:
    """Chuyển tiếp request tới service và ghi lại mọi lần chạy."""

    def __init__(self, registry: ServiceRegistry, session_factory, timeout_s: float = 120.0):
        self._registry = registry
        self._factory = session_factory
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def fetch(self, uri: str) -> bytes:
        try:
            response = await self._client.get(uri)
        except (httpx.UnsupportedProtocol, httpx.InvalidURL) as exc:
            # PHẢI bắt TRƯỚC TransportError: UnsupportedProtocol kế thừa từ nó.
            # URI sai scheme hay sai định dạng thì thử lại bao nhiêu lần cũng
            # hỏng y hệt — xếp vào hạ tầng sẽ làm consumer pause vô hạn và kẹt
            # cả partition sau một URI hỏng, trong khi DLQ vẫn rỗng.
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"URI không dùng được: {uri} ({exc})", 422
            ) from exc
        if response.status_code >= 400:
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"tải {uri} thất bại ({response.status_code})", 422
            )
        return response.content

    async def invoke(
        self, service: str, data: bytes, filename: str,
        model_version: str | None, trace_id: str | None = None,
    ) -> RunRecord:
        # Ranh giới ghi `runs`: những lần TỪ CHỐI phía gateway (không có service,
        # chưa từng poll được, đã biết là DOWN) KHÔNG tạo dòng nào — chưa có gì
        # chạy nên chưa có gì để ghi lịch sử. Từ lúc đã gửi request đi thì mọi
        # kết cục, kể cả hỏng, đều phải có một dòng.
        state = self._registry.get(service)
        if state is None:
            raise ServiceError(ErrorCode.BAD_INPUT, f"không có service '{service}'", 404)
        if state.info is None:
            # Chưa poll được lần nào nên chưa biết invoke_path. Đoán đường gọi là
            # gửi request vào hư không rồi báo lỗi ở chỗ chẳng liên quan.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"gateway chưa liên hệ được '{service}' lần nào, chưa biết đường gọi",
                503,
            )
        if state.status is HealthStatus.DOWN:
            # Đã biết nó chết thì đừng gửi vào: trả 503 ngay, nói rõ lý do,
            # thay vì để caller chờ hết timeout rồi nhận lỗi mơ hồ.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"service '{service}' đang không phản hồi", 503
            )

        trace = trace_id or uuid.uuid4().hex
        url = f"{state.base_url.rstrip('/')}{state.info.invoke_path}"
        form = {"model_version": model_version} if model_version else {}
        started = time.monotonic()
        status, output, error, resolved = RunStatus.FAILED, None, None, model_version
        try:
            response = await self._client.post(
                url,
                data=form,
                files={"file": (filename, data, "application/octet-stream")},
                headers={"x-trace-id": trace},
            )
            if response.status_code >= 400:
                error = f"service trả {response.status_code}: {response.text[:200]}"
            else:
                body = response.json()
                output = body.get("result")
                resolved = body.get("model_version") or model_version
                status = RunStatus.OK
        except Exception as exc:
            error = str(exc)

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            async with self._factory() as session:
                record = await RunRepo(session).record(
                    trace_id=trace, service=service, model_version=resolved,
                    mode=InvokeMode.SYNC, status=status, input_uri=None,
                    output=output, latency_ms=latency_ms, error=error,
                    # Đường sync tôn trọng x-trace-id do CALLER chọn. Dedup
                    # theo (trace_id, model_version) là đúng khi trace_id do
                    # Kafka phát ra (đường async/result_consumer), nhưng với
                    # trace_id do client chọn thì trùng nghĩa là hai request
                    # KHÁC NHAU tình cờ/chủ đích trùng header — trả lại row cũ
                    # là ÂM THẦM TRẢ NHẦM KẾT QUẢ cho caller thứ hai (INVOICE B
                    # chạy xong, GPU tốn thời gian, nhưng caller nhận INVOICE
                    # A). Ép record() từ chối thay vì dedup ở đúng nhánh gọi
                    # này.
                    reject_duplicate_trace=True,
                )
        except ServiceError:
            # ServiceError là lỗi ĐÃ ĐƯỢC PHÂN LOẠI ĐÚNG bởi chính record() ở
            # trên (trace_id trùng là lỗi của CLIENT, không phải hạ tầng) —
            # để nó bay thẳng ra, không phải chạy tiếp vào nhánh except Exception
            # bên dưới rồi bị gán nhầm thành 503 hạ tầng.
            raise
        except Exception as exc:
            # Cùng lỗ hổng như result_consumer.py: DB không kết nối được (ổ cắm
            # chết, container restart) ném OSError trần, không phải
            # SQLAlchemyError — allowlist theo kiểu exception đã lọt bug này
            # bốn lần trước rồi trên nhánh kia. Ở đây mọi lỗi của khối ghi DB
            # (trừ ServiceError đã bắt ở trên) đều là hạ tầng: một kết quả
            # inference ĐÃ CHẠY XONG không được phép biến thành 500 mù mờ —
            # phải là 503 nói rõ lý do.
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR, f"không ghi được run vào DB: {exc}", 503
            ) from exc
        if status is RunStatus.FAILED:
            # Ghi xong rồi mới ném: lỗi là lúc lịch sử có giá trị nhất.
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, error or "service lỗi", 502)
        return record

    async def aclose(self) -> None:
        await self._client.aclose()
