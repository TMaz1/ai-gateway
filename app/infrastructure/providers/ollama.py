import json

import httpx

from app.ai.provider import GenerationRequest, GenerationResponse


class ProviderUnavailableError(RuntimeError):
    """The configured provider could not complete a generation request."""


class ProviderResponseTooLargeError(ProviderUnavailableError):
    """The provider response exceeded the configured byte limit."""


class OllamaProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_response_bytes: int,
        max_output_tokens: int,
    ) -> None:
        if not model or model.strip() != model:
            raise ValueError("Ollama model must be a non-empty configured value.")
        if max_response_bytes < 1 or max_output_tokens < 1:
            raise ValueError("Provider resource limits must be positive.")

        self._client = client
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_output_tokens = max_output_tokens

    async def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResponse:
        capability = request.capability
        message = request.user_input["message"]

        payload = {
            "model": self._model,
            "stream": False,
            "format": capability.output_schema,
            "options": {
                "temperature": capability.temperature,
                "num_predict": min(
                    capability.max_output_tokens,
                    self._max_output_tokens,
                ),
            },
            "messages": [
                {"role": "system", "content": capability.instructions},
                {"role": "user", "content": message},
            ],
        }

        try:
            async with self._client.stream(
                "POST",
                self._url,
                json=payload,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    raise ProviderUnavailableError(
                        "The configured provider returned a redirect."
                    )

                if response.status_code >= 400:
                    raise ProviderUnavailableError(
                        "The configured provider returned an error."
                    )

                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise ProviderUnavailableError(
                            "Provider returned an invalid response length."
                        ) from exc

                    if declared_length < 0:
                        raise ProviderUnavailableError(
                            "Provider returned an invalid response length."
                        )
                    if declared_length > self._max_response_bytes:
                        raise ProviderResponseTooLargeError(
                            "Provider response exceeded its configured limit."
                        )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self._max_response_bytes:
                        raise ProviderResponseTooLargeError(
                            "Provider response exceeded its configured limit."
                        )
                    chunks.append(chunk)

            try:
                envelope = json.loads(b"".join(chunks))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderUnavailableError(
                    "Provider returned an invalid response."
                ) from exc

            if not isinstance(envelope, dict):
                raise ProviderUnavailableError("Provider returned an invalid response.")

            message_obj = envelope.get("message")
            if not isinstance(message_obj, dict):
                raise ProviderUnavailableError("Provider returned an invalid response.")

            content = message_obj.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ProviderUnavailableError(
                    "Provider returned empty generation content."
                )

            return GenerationResponse(content=content, model=self._model)

        except ProviderUnavailableError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                "The configured provider timed out."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The configured provider could not be reached."
            ) from exc
