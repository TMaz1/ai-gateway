from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application configuration.

    Security-sensitive and environment-specific values are deliberately
    configuration-driven rather than embedded in application code.
    """

    environment: str = "development"

    host: str = "127.0.0.1"

    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
    )

    log_level: str = "INFO"

    database_path: str = "./data/gateway.db"

    api_key_pepper: str = "development-only-change-me"

    ollama_base_url: str = "http://127.0.0.1:11434"

    provider_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
    )

    max_request_body_bytes: int = Field(
        default=32768,
        gt=0,
        le=10_485_760,
    )

    max_message_chars: int = Field(
        default=8000,
        gt=0,
        le=1_000_000,
    )

    max_estimated_input_tokens: int = Field(
        default=2048,
        gt=0,
        le=1_000_000,
    )

    max_output_tokens: int = Field(
        default=256,
        gt=0,
        le=1_000_000,
    )

    max_provider_response_bytes: int = Field(
        default=65536,
        gt=0,
        le=10_485_760,
    )

    max_concurrent_global: int = Field(
        default=16,
        gt=0,
        le=10_000,
    )

    max_concurrent_per_key: int = Field(
        default=4,
        gt=0,
        le=10_000,
    )

    rate_limit_requests: int = Field(
        default=30,
        gt=0,
        le=1_000_000,
    )

    rate_limit_window_seconds: int = Field(
        default=60,
        gt=0,
        le=86_400,
    )

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

        allowed = {
            "development",
            "test",
            "production",
        }

        if normalized not in allowed:
            raise ValueError(
                "environment must be one of: development, test, production"
            )

        return normalized

    @field_validator("ollama_base_url")
    @classmethod
    def validate_provider_url(cls, value: str) -> str:
        """
        Validate provider configuration.

        This does not permit callers to supply URLs; it only validates the
        trusted operator configuration.
        """
        value = value.strip().rstrip("/")

        if not value.startswith(("http://", "https://")):
            raise ValueError("provider URL must use HTTP or HTTPS")

        return value

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("database path cannot be empty")

        return value

    @field_validator("api_key_pepper")
    @classmethod
    def validate_pepper(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError(
                "API-key pepper must be at least 16 characters"
            )

        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if (
            self.environment == "production"
            and self.api_key_pepper == "development-only-change-me"
        ):
            raise ValueError(
                "production requires a non-default API-key pepper"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """
    Return the process-wide settings instance.

    Tests can call get_settings.cache_clear() before constructing an isolated
    application with different environment variables.
    """
    return Settings()