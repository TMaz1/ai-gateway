from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.application.api_key_service import ApiKeyService
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
        # Avoid creating files or opening the database during module import.
        database.initialize()

        key_repository = SqliteApiKeyRepository(database)
        events = SqliteSecurityEventRepository(database)

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

        try:
            yield
        finally:
            # SQLite connections are scoped to repository operations.
            for name in (
                "api_key_service",
                "security_events",
                "database",
                "rate_limiter",
                "concurrency_limiter",
            ):
                if hasattr(app.state, name):
                    delattr(app.state, name)

    app = FastAPI(
        title="AI Gateway",
        version="0.2.0",
        description=(
            "A policy-enforcing gateway foundation for text-focused AI capabilities."
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

    # Middleware is added in reverse wrapping order: request IDs must be
    # outermost so early body-limit responses also carry the request ID.
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health_router)
    return app


app = create_app()
