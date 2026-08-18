from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from vypq_core.config import BaseServiceSettings
from vypq_core.host_registry import HostRef


class OcrSettings(BaseServiceSettings):
    service_name: str = "ocr"
    port: int = 8001
    default_model: str = "paddleocr-v4-vi"
    max_side: int = 2000
    timeout_s: float = 60.0
    hosts_path: Path = Path("config.yaml")
    brokers: str = "localhost:9092"
    group_prefix: str = "ocr"
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
