import re
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[[dict[str, Any], Callable, Callable], Awaitable[None]]
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def new_request_id() -> str:
    return secrets.token_hex(16)


class RequestIdMiddleware:
    """Pure ASGI request-ID middleware for normal and early responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = (
            dict(scope.get("headers", [])).get(b"x-request-id", b"").decode("latin-1")
        )
        request_id = (
            incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else new_request_id()
        )

        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [
                    (key, value)
                    for key, value in headers
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_with_id)
