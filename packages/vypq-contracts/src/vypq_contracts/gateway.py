from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.hosting import ModelInfo


class HostRegistration(BaseModel):
    """Thân request khi đăng ký một máy GPU vừa thuê."""

    name: str
    url: str
    token: str | None = None


class HostState(BaseModel):
    """Trạng thái một host như gateway đang thấy.

    KHÔNG mang `token`: gateway giữ token trong DB và cấp riêng cho service qua
    đường khác. Nhét nó vào đây là phát bí mật kèm mọi lần liệt kê host.
    """

    name: str
    url: str
    # Mặc định False: máy vừa đăng ký chưa poll lần nào thì "chưa biết", và
    # chưa biết phải nghiêng về không định tuyến vào.
    healthy: bool = False
    models: list[ModelInfo] = Field(default_factory=list)
    last_seen_at: datetime | None = None
    last_error: str | None = None


class HostsResponse(BaseModel):
    hosts: list[HostState] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    """Service tự mô tả mình — gateway lấy qua GET /v1/info."""

    name: str
    task: Task
    capability_input: str
    capability_output: str
    version: str
    # Đường nhận multipart để chạy inference, ví dụ "/v1/ocr". Service TỰ khai
    # chứ gateway không suy ra từ tên hay task: Plan A hardcode "/v1/ocr", còn
    # service sinh từ template có thể đặt khác. Đoán ở đây là gọi sai đường.
    invoke_path: str
    default_model: str | None = None


class ServiceState(BaseModel):
    """Trạng thái một service như gateway đang thấy.

    `name` là KHOÁ ĐỊNH TUYẾN — tên trong `config/services.yaml`, thứ duy nhất
    gateway tra cứu khi nhận `POST /v1/invoke`. Nó KHÔNG nhất thiết bằng
    `info.name` (tên service tự khai qua /v1/info): hai chỗ đó do hai người
    khác nhau đặt, và trước khi có trường này, dashboard gọi bằng `info.name`
    nên chỉ cần ai đó đổi một trong hai là mọi lần chạy thử trả 404 "không có
    service", còn trang lịch sử thì hiện JSON thô thay vì viewer đúng — im
    lặng, vì không chỗ nào đối chiếu hai tên.
    """

    name: str
    # None nghĩa là gateway CHƯA TỪNG poll thành công service này — không có
    # ServiceInfo thật để đọc, nên tuyệt đối không được đoán task hay
    # invoke_path (đoán = có thể gọi/định tuyến sai service, ví dụ publish
    # nhầm sang topic Kafka của task khác).
    info: ServiceInfo | None = None
    base_url: str
    status: HealthStatus = HealthStatus.DOWN
    last_seen_at: datetime | None = None


class ServicesResponse(BaseModel):
    services: list[ServiceState] = Field(default_factory=list)


class InvokeMode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"


class InvokeRequest(BaseModel):
    service: str
    model_version: str | None = None
    mode: InvokeMode = InvokeMode.SYNC
    input_uri: str | None = None


class InvokeResponse(BaseModel):
    trace_id: str
    mode: InvokeMode
    run_id: str | None = None
    result: dict[str, Any] | None = None


class RunStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class RunRecord(BaseModel):
    id: str
    trace_id: str
    service: str
    model_version: str | None = None
    mode: InvokeMode
    status: RunStatus
    input_uri: str | None = None
    output: dict[str, Any] | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: datetime

    @field_validator("model_version", mode="before")
    @classmethod
    def _empty_means_unknown(cls, value: str | None) -> str | None:
        """Chuỗi rỗng và None là cùng một ý: chưa biết model nào.

        Tầng DB buộc phải lưu "" chứ không NULL, vì SQL coi mọi NULL là khác
        nhau nên khoá duy nhất (trace_id, model_version) sẽ không chặn được gì.
        Không chuẩn hoá ở đây thì code phía sau kiểm `is None` sẽ trượt với
        đúng những dòng đọc lên từ DB.
        """
        return value or None


class RunsResponse(BaseModel):
    runs: list[RunRecord] = Field(default_factory=list)
    total: int = 0
