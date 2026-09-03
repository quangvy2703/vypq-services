from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VYPQ_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: str = "unnamed"
    version: str = "0.1.0"
    log_level: str = "INFO"
    port: int = 8000
    # Hai chốt cho MỌI chỗ tự tải input_uri (gateway, worker của service,
    # model-host). Để ở đây chứ không khai lại ba lần: chúng chặn cùng một
    # đường tấn công — một URL do người ngoài đưa vào, trỏ tới file lớn tuỳ ý.
    max_download_mb: int = 100
    fetch_deadline_s: float = 60.0
