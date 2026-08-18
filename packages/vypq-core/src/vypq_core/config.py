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
