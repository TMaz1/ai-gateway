import asyncio
import json

import httpx
import pytest

from app.ai.capabilities import CapabilityRegistry
from app.ai.provider import GenerationRequest
from app.infrastructure.providers.ollama import (
    OllamaProvider,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
)


def _request() -> GenerationRequest:
    definition = CapabilityRegistry().require("support_intent")
    return GenerationRequest(
        capability=definition,
        user_input={"message": "I think I was charged twice."},
    )


def _provider(handler, *, max_response_bytes=4096, max_output_tokens=128):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OllamaProvider(
        client=client,
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=2,
        max_response_bytes=max_response_bytes,
        max_output_tokens=max_output_tokens,
    )
    return provider, client


def test_ollama_adapter_sends_trusted_schema_and_model():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"content": '{"category":"duplicate_charge_concern"}'}},
        )

    async def run():
        provider, client = _provider(handler)
        try:
            response = await provider.generate(_request())
            return response
        finally:
            await client.aclose()

    result = asyncio.run(run())

    payload = seen["payload"]
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert payload["model"] == "qwen2.5:1.5b"
    assert payload["stream"] is False
    assert payload["format"]["properties"]["category"]["enum"]
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == ("I think I was charged twice.")
    assert result.content == '{"category":"duplicate_charge_concern"}'
    assert result.model == "qwen2.5:1.5b"


def test_ollama_adapter_rejects_redirects():
    def handler(request):
        return httpx.Response(302, headers={"Location": "http://evil.test/"})

    async def run():
        provider, client = _provider(handler)
        try:
            with pytest.raises(ProviderUnavailableError):
                await provider.generate(_request())
        finally:
            await client.aclose()

    asyncio.run(run())


def test_ollama_adapter_rejects_provider_error_status():
    def handler(request):
        return httpx.Response(500, text="internal provider details")

    async def run():
        provider, client = _provider(handler)
        try:
            with pytest.raises(ProviderUnavailableError):
                await provider.generate(_request())
        finally:
            await client.aclose()

    asyncio.run(run())


def test_ollama_adapter_bounds_provider_response_size():
    def handler(request):
        return httpx.Response(
            200,
            content=b"x" * 2048,
            headers={"content-type": "application/json"},
        )

    async def run():
        provider, client = _provider(handler, max_response_bytes=64)
        try:
            with pytest.raises(ProviderResponseTooLargeError):
                await provider.generate(_request())
        finally:
            await client.aclose()

    asyncio.run(run())


def test_ollama_adapter_rejects_invalid_envelope():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    async def run():
        provider, client = _provider(handler)
        try:
            with pytest.raises(ProviderUnavailableError):
                await provider.generate(_request())
        finally:
            await client.aclose()

    asyncio.run(run())


def test_ollama_adapter_does_not_follow_redirects():
    def handler(request):
        return httpx.Response(307, headers={"Location": "/other"})

    async def run():
        provider, client = _provider(handler)
        try:
            with pytest.raises(ProviderUnavailableError):
                await provider.generate(_request())
        finally:
            await client.aclose()

    asyncio.run(run())
