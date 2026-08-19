from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from vypq_core.config import BaseServiceSettings
from vypq_core.host_registry import DiscoveryHostRegistry, HostRef, HostRegistry, StaticHostRegistry
from vypq_core.logging import get_logger

log = get_logger(__name__)


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


def build_host_registry(settings: AsrSettings) -> HostRegistry:
    """Dựng registry theo `host_discovery.source`.

    Đây là toàn bộ chi phí của việc chuyển từ danh sách tĩnh sang discovery
    động: một dòng trong config, không dòng nào trong logic service.
    """
    if not settings.hosts_path.is_file():
        return StaticHostRegistry([])
    parsed = HostsFile.model_validate(
        yaml.safe_load(settings.hosts_path.read_text(encoding="utf-8"))
    )
    discovery = parsed.host_discovery
    if discovery.source == "gateway" and discovery.url:
        return DiscoveryHostRegistry(
            discovery.url,
            refresh_s=discovery.refresh_s,
            fallback=discovery.fallback_static,
        )
    # source=gateway mà thiếu url là cấu hình sai; rơi về static còn hơn ném
    # lúc khởi động và làm service không lên được. Nhưng im lặng thì operator
    # tưởng đang theo gateway trong khi thực ra chạy danh sách tĩnh cũ — phải
    # log để còn biết mà sửa config.
    if discovery.source == "gateway":
        log.warning(
            "host_discovery_gateway_missing_url",
            fallback="static",
            fallback_hosts=len(discovery.fallback_static),
        )
    return StaticHostRegistry(discovery.fallback_static)
