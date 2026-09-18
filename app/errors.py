from fastapi import Request
from fastapi.responses import JSONResponse


async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Return a safe generic error.

    Internal exceptions are deliberately not reflected in the HTTP response.
    The request ID gives operators a correlation mechanism without exposing
    stack traces, filesystem paths, SQL, or provider internals.
    """
    request_id = getattr(request.state, "request_id", None)

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected internal error occurred.",
            },
            "requestId": request_id,
        },
    )