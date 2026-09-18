from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.configuration.settings import get_settings
from app.infrastructure.persistence.database import Database
from app.logging_config import configure_logging
from app.middleware.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    """
    Application factory.

    Keeping application construction in a factory makes the application easier
    to test because tests can construct isolated instances with different
    environment/configuration settings.
    """
    settings = get_settings()

    configure_logging(settings.log_level)

    database = Database(settings.database_path)
    database.initialize()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.database = database

        yield

    app = FastAPI(
        title="AI Gateway",
        version="0.1.0",
        description=(
            "A policy-enforcing gateway foundation for text-focused AI "
            "capabilities."
        ),
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)

    app.include_router(health_router)

    return app


app = create_app()