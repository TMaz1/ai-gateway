import json
from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[[dict[str, Any], Callable, Callable], Awaitable[None]]
_JSON_METHODS = {"POST", "PUT", "PATCH"}


class RequestBodyLimitMiddleware:
    """Bound request bodies before routing, including chunked request bodies."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")

        if raw_length is not None:
            try:
                declared_length = int(raw_length)
                if declared_length < 0:
                    raise ValueError
            except ValueError:
                await self._reject(
                    scope,
                    send,
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "Invalid Content-Length header.",
                )
                return

            if declared_length > self.max_body_bytes:
                await self._reject(
                    scope,
                    send,
                    413,
                    "REQUEST_TOO_LARGE",
                    "Request body exceeds the configured limit.",
                )
                return

        chunks: list[bytes] = []
        total = 0

        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                return

            chunk = message.get("body", b"")
            total += len(chunk)

            if total > self.max_body_bytes:
                await self._reject(
                    scope,
                    send,
                    413,
                    "REQUEST_TOO_LARGE",
                    "Request body exceeds the configured limit.",
                )
                return

            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)

        if scope.get("method", "GET").upper() in _JSON_METHODS and body:
            content_type = (
                headers.get(b"content-type", b"")
                .decode("latin-1")
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            is_json = content_type == "application/json"
            is_json_suffix = content_type.startswith(
                "application/"
            ) and content_type.endswith("+json")

            if not (is_json or is_json_suffix):
                await self._reject(
                    scope,
                    send,
                    415,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "Request body must use a JSON media type.",
                )
                return

        delivered = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal delivered

            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }

            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(
        scope: dict[str, Any],
        send: Callable,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        state = scope.get("state") or {}
        request_id = state.get("request_id")

        payload = json.dumps(
            {
                "error": {"code": code, "message": message},
                "requestId": request_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
            }
        )
