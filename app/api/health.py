from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(
    tags=["health"],
)


@router.get("/health")
async def health() -> dict[str, str]:
    """
    Liveness endpoint.

    This deliberately does not expose infrastructure information.
    """
    return {
        "status": "ok",
    }


@router.get("/health/ready")
async def readiness(
    request: Request,
):
    """
    Readiness endpoint.

    Batch 1 verifies the SQLite dependency because it is currently the only
    required persistence dependency.

    Provider readiness is deliberately not exposed here yet; provider
    integration arrives in a later batch.
    """
    try:
        database = request.app.state.database

        with database.connection() as connection:
            connection.execute(
                "SELECT 1"
            ).fetchone()

        return {
            "status": "ready",
        }

    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
            },
        )