from pathlib import Path

from pydantic import field_validator
from vypq_core.config import BaseServiceSettings


class ModelHostSettings(BaseServiceSettings):
    service_name: str = "model-host"
    host_name: str = "gpu-1"
    token: str = ""
    models_path: Path = Path("models.yaml")
    port: int = 9000

    @field_validator("token")
    @classmethod
    def _token_must_not_be_empty(cls, value: str) -> str:
        # ngrok phơi endpoint ra Internet công cộng: chạy không token là không chấp nhận được.
        if not value.strip():
            raise ValueError("VYPQ_TOKEN bắt buộc phải có — model-host từ chối khởi động")
        return value
