"""Application settings from environment / ``.env`` (no in-code defaults)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str
    log_level: str

    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_user: str
    rabbitmq_password: str

    retry_exchange: str
    retry_exchange_type: str
    retry_queue: str
    retry_queue_binding_key: str

    retry_delay_exchange: str
    retry_delay_queue: str

    events_exchange: str

    dlq_exchange: str
    dlq_queue: str
    dlq_routing_key: str

    rabbitmq_prefetch: int
    max_retries: int

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def rabbitmq_url(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/"
        )


settings = Settings()
