import re
import secrets

from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_REQUEST_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)


def new_request_id() -> str:
    """
    Generate a non-secret correlation ID.
    """
    return secrets.token_hex(16)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Attach a bounded request/correlation ID to every request.

    Caller-supplied IDs are accepted only when they conform to a conservative
    character/length policy. Otherwise the gateway generates a new ID.
    """

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        incoming = request.headers.get("X-Request-ID")

        if (
            incoming
            and _REQUEST_ID_PATTERN.fullmatch(incoming)
        ):
            request_id = incoming
        else:
            request_id = new_request_id()

        request.state.request_id = request_id

        response = await call_next(request)

        headers = MutableHeaders(response.headers)
        headers["X-Request-ID"] = request_id

        return response