import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    database_path: str = "./data/gateway.db"
    api_key_pepper: str = "development-only-change-me"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_allowed_hosts: str = "127.0.0.1,localhost,::1"
    ollama_model: str = "qwen2.5:1.5b"
    provider_timeout_seconds: float = Field(default=120.0, gt=0, le=300)

    max_request_body_bytes: int = Field(default=32768, gt=0, le=10_485_760)
    max_message_chars: int = Field(default=8000, gt=0, le=1_000_000)
    max_estimated_input_tokens: int = Field(default=2048, gt=0, le=1_000_000)
    max_output_tokens: int = Field(default=256, gt=0, le=1_000_000)
    max_provider_response_bytes: int = Field(default=65536, gt=0, le=10_485_760)

    max_concurrent_global: int = Field(default=16, gt=0, le=10_000)
    max_concurrent_per_key: int = Field(default=4, gt=0, le=10_000)

    rate_limit_requests: int = Field(default=30, gt=0, le=1_000_000)
    rate_limit_window_seconds: int = Field(default=60, gt=0, le=86_400)
    rate_limit_max_tracked_keys: int = Field(default=10_000, gt=100, le=1_000_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GATEWAY_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test, or production")
        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("log level is invalid")
        return normalized

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("database path cannot be empty")
        return value.strip()

    @field_validator("api_key_pepper")
    @classmethod
    def validate_pepper(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("API-key pepper must be at least 16 characters")
        return value

    @field_validator("ollama_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("Ollama model name is invalid")
        return normalized

    @field_validator("ollama_base_url")
    @classmethod
    def validate_provider_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("provider URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("provider URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("provider URL must not contain query or fragment data")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("provider URL contains an invalid port") from exc

        return value

    @field_validator("ollama_allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        hosts = [item.strip().lower() for item in value.split(",") if item.strip()]
        if not hosts:
            raise ValueError("Ollama allowed-host list cannot be empty")
        return ",".join(hosts)

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if (
            self.environment == "production"
            and self.api_key_pepper == "development-only-change-me"
        ):
            raise ValueError("production requires a non-default API-key pepper")

        parsed = urlsplit(self.ollama_base_url)
        host = (parsed.hostname or "").lower()
        allowed = {
            item.strip().lower() for item in self.ollama_allowed_hosts.split(",")
        }
        if host not in allowed:
            raise ValueError("provider host is not in GATEWAY_OLLAMA_ALLOWED_HOSTS")

        is_loopback = host == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass

        if (
            self.environment == "production"
            and parsed.scheme != "https"
            and not is_loopback
        ):
            raise ValueError("production provider URLs must use HTTPS unless loopback")

        if self.max_concurrent_per_key > self.max_concurrent_global:
            raise ValueError("per-key concurrency limit cannot exceed global limit")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
