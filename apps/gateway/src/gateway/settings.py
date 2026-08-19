from pathlib import Path

from pydantic import field_validator
from vypq_core.config import BaseServiceSettings


class GatewaySettings(BaseServiceSettings):
    service_name: str = "gateway"
    port: int = 8080
    token: str = ""
    database_url: str = "postgresql+asyncpg://vypq:vypq@localhost:5432/vypq"
    brokers: str = "localhost:9092"
    services_path: Path = Path("config/services.yaml")
    poll_interval_s: float = 15.0
    # Quá hạn này mà không poll thành công thì host bị coi là chết và gỡ khỏi
    # định tuyến. Gấp 3 chu kỳ poll: một lần trượt vì mạng chập không nên hạ máy.
    host_ttl_s: float = 45.0
    # Mặc định TẮT, giống model-host: /docs và /openapi.json phơi nguyên sơ đồ
    # route + schema cho bất kỳ ai chạm được cổng. Gateway đứng giữa Internet
    # và token của mọi host GPU đang thuê, nên đây không phải nơi để mặc định
    # bật cho tiện dev.
    expose_docs: bool = False

    @field_validator("token")
    @classmethod
    def _token_must_not_be_empty(cls, value: str) -> str:
        # Gateway phơi /v1/discovery/hosts (mang token của mọi host GPU) và
        # /v1/hosts (POST cho phép trỏ lại một host đang thuê). Chạy không
        # token là đúng thứ mà thay đổi này tồn tại để ngăn — từ chối khởi
        # động, không cảnh báo rồi chạy tiếp.
        if not value.strip():
            raise ValueError("VYPQ_TOKEN bắt buộc phải có — gateway từ chối khởi động")
        return value
