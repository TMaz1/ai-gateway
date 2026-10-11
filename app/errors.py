import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_STATUS_MESSAGES = {
    400: ("BAD_REQUEST", "The request is invalid."),
    401: ("UNAUTHORIZED", "A valid gateway API key is required."),
    403: ("FORBIDDEN", "The API key is not authorized for this operation."),
    404: ("NOT_FOUND", "The requested resource was not found."),
    413: ("REQUEST_TOO_LARGE", "Request body exceeds the configured limit."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Request body must use a JSON media type."),
    422: ("VALIDATION_ERROR", "Request validation failed."),
    429: ("RATE_LIMITED", "Request rate limit exceeded."),
    503: ("SERVICE_UNAVAILABLE", "The service is temporarily unavailable."),
}


def _payload(request: Request, code: str, message: str) -> dict:
    return {
        "error": {"code": code, "message": message},
        "requestId": getattr(request.state, "request_id", None),
    }


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code, message = _STATUS_MESSAGES.get(
        exc.status_code,
        ("HTTP_ERROR", "The request could not be completed."),
    )

    if (
        exc.status_code == 429
        and isinstance(exc.detail, dict)
        and exc.detail.get("code") == "CONCURRENCY_LIMITED"
    ):
        code, message = (
            "CONCURRENCY_LIMITED",
            "Request concurrency limit exceeded.",
        )

    # Preserve protocol headers but never reflect raw exception details.
    headers = {
        **(exc.headers or {}),
        "X-Request-ID": str(getattr(request.state, "request_id", "")),
    }

    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(request, code, message),
        headers=headers,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_payload(
            request,
            "VALIDATION_ERROR",
            "Request validation failed.",
        ),
        headers={
            "X-Request-ID": str(getattr(request.state, "request_id", "")),
        },
    )


async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "unhandled_request_error request_id=%s",
        getattr(request.state, "request_id", None),
    )

    return JSONResponse(
        status_code=500,
        content=_payload(
            request,
            "INTERNAL_ERROR",
            "An unexpected internal error occurred.",
        ),
        headers={
            "X-Request-ID": str(getattr(request.state, "request_id", "")),
        },
    )
