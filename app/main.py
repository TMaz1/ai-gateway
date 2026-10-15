from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.capabilities import CapabilityRegistry
from app.api.classification import router as classification_router
from app.api.health import router as health_router
from app.application.api_key_service import ApiKeyService
from app.application.classification_service import ClassificationService
from app.configuration.settings import get_settings
from app.errors import (
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.infrastructure.providers.ollama import OllamaProvider
from app.logging_config import configure_logging
from app.middleware.body_limit import RequestBodyLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.security.api_keys import ApiKeyManager
from app.security.concurrency import ConcurrencyLimiter
from app.security.rate_limiter import InMemoryRateLimiter


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()

        key_repository = SqliteApiKeyRepository(database)
        events = SqliteSecurityEventRepository(database)
        registry = CapabilityRegistry()

        app.state.settings = settings
        app.state.database = database
        app.state.security_events = events
        app.state.api_key_service = ApiKeyService(
            key_repository,
            events,
            ApiKeyManager(settings.api_key_pepper),
        )
        app.state.rate_limiter = InMemoryRateLimiter(
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
            settings.rate_limit_max_tracked_keys,
        )
        app.state.concurrency_limiter = ConcurrencyLimiter(
            settings.max_concurrent_global,
            settings.max_concurrent_per_key,
        )
        app.state.capability_registry = registry

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.provider_timeout_seconds),
            follow_redirects=False,
        ) as client:
            provider = OllamaProvider(
                client=client,
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=settings.provider_timeout_seconds,
                max_response_bytes=settings.max_provider_response_bytes,
                max_output_tokens=settings.max_output_tokens,
            )
            app.state.provider = provider
            app.state.classification_service = ClassificationService(
                registry=registry,
                provider=provider,
                max_message_chars=settings.max_message_chars,
                max_estimated_input_tokens=(settings.max_estimated_input_tokens),
            )

            try:
                yield
            finally:
                for name in (
                    "classification_service",
                    "provider",
                    "capability_registry",
                    "api_key_service",
                    "security_events",
                    "database",
                    "rate_limiter",
                    "concurrency_limiter",
                    "settings",
                ):
                    if hasattr(app.state, name):
                        delattr(app.state, name)

    app = FastAPI(
        title="AI Gateway",
        version="0.3.0",
        description=(
            "A policy-enforcing gateway for trusted, text-focused AI capabilities."
        ),
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
        exception_handlers={
            StarletteHTTPException: http_error_handler,
            RequestValidationError: validation_error_handler,
            Exception: unexpected_error_handler,
        },
    )

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health_router)
    app.include_router(classification_router)

    return app


app = create_app()
