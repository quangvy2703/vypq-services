from pathlib import Path

from vypq_core.config import BaseServiceSettings


class GatewaySettings(BaseServiceSettings):
    service_name: str = "gateway"
    port: int = 8080
    database_url: str = "postgresql+asyncpg://vypq:vypq@localhost:5432/vypq"
    brokers: str = "localhost:9092"
    services_path: Path = Path("config/services.yaml")
    poll_interval_s: float = 15.0
    # Quá hạn này mà không poll thành công thì host bị coi là chết và gỡ khỏi
    # định tuyến. Gấp 3 chu kỳ poll: một lần trượt vì mạng chập không nên hạ máy.
    host_ttl_s: float = 45.0
