from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from vypq_core.config import BaseServiceSettings
from vypq_core.host_registry import HostRef


class AsrSettings(BaseServiceSettings):
    service_name: str = "asr"
    port: int = 8002
    default_model: str = "asr-model-v1"
    timeout_s: float = 60.0
    hosts_path: Path = Path("config.yaml")
    brokers: str = "localhost:9092"
    # Prefix theo SLUG, không phải task. Hai service khác nhau cùng đọc một topic
    # (ví dụ ocr và ocr-handwriting) là hai pipeline riêng, mỗi bên phải nhận đủ
    # mọi message — chung group thì Kafka chia partition và mỗi bên chỉ thấy một
    # phần, im lặng. Nhiều instance của CÙNG một service thì chung group là đúng,
    # đó mới là chia tải.
    group_prefix: str = "asr"
    model_version: str | None = None  # VYPQ_MODEL_VERSION — đặt để bật shadow-run


class HostDiscovery(BaseModel):
    source: str = "static"
    url: str | None = None
    refresh_s: int = 15
    fallback_static: list[HostRef] = Field(default_factory=list)


class HostsFile(BaseModel):
    host_discovery: HostDiscovery = Field(default_factory=HostDiscovery)


def load_hosts(path: Path) -> list[HostRef]:
    """Plan A chỉ đọc fallback_static. Plan B thêm nhánh source == 'gateway'."""
    if not path.is_file():
        return []
    parsed = HostsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return parsed.host_discovery.fallback_static
