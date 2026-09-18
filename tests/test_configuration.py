import pytest
from pydantic import ValidationError

from app.configuration.settings import Settings


def test_production_rejects_default_pepper():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
        )


def test_invalid_provider_url_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            ollama_base_url="ftp://example.com",
        )


def test_invalid_timeout_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            provider_timeout_seconds=0,
        )


def test_negative_rate_limit_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            rate_limit_requests=-1,
        )


def test_zero_concurrency_limit_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            max_concurrent_global=0,
        )


def test_empty_database_path_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            database_path="   ",
        )


def test_short_pepper_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            api_key_pepper="too-short",
        )


def test_supported_environment_is_accepted():
    settings = Settings(
        environment="test",
        api_key_pepper="a-secure-test-pepper",
    )

    assert settings.environment == "test"