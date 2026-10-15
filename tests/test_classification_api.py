import json

from fastapi.testclient import TestClient

from app.ai.provider import GenerationResponse
from app.configuration.settings import get_settings
from app.infrastructure.providers.ollama import OllamaProvider
from app.main import create_app


def _configure(monkeypatch, tmp_path):
    values = {
        "GATEWAY_ENVIRONMENT": "test",
        "GATEWAY_DATABASE_PATH": str(tmp_path / "gateway.db"),
        "GATEWAY_API_KEY_PEPPER": "a-secure-test-pepper-value",
        "GATEWAY_RATE_LIMIT_REQUESTS": "20",
        "GATEWAY_MAX_REQUEST_BODY_BYTES": "32768",
        "GATEWAY_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "GATEWAY_OLLAMA_ALLOWED_HOSTS": "127.0.0.1,localhost,::1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _create_key(app, capability="support_intent"):
    _, plaintext = app.state.api_key_service.create(
        client_name="classification-test",
        capabilities=frozenset({capability}),
    )
    return plaintext


def test_classify_requires_authentication(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/ai/classify",
            json={
                "capability": "support_intent",
                "message": "I was charged twice.",
            },
        )
        assert response.status_code == 401

    get_settings.cache_clear()


def test_classify_returns_schema_validated_result(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    calls = {"count": 0}

    async def fake_generate(self, request):
        calls["count"] += 1
        return GenerationResponse(
            content=json.dumps({"category": "duplicate_charge_concern"}),
            model="fake-model",
        )

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app)
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "support_intent",
                "message": "I think I was charged twice.",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "capability": "support_intent",
            "category": "duplicate_charge_concern",
        }
        assert calls["count"] == 1

    get_settings.cache_clear()


def test_unknown_capability_is_rejected_before_provider_call(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    calls = {"count": 0}

    async def fake_generate(self, request):
        calls["count"] += 1
        return GenerationResponse(
            content='{"category":"other"}',
            model="fake-model",
        )

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app)
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "arbitrary-client-selected-model",
                "message": "Hello",
            },
        )

        assert response.status_code == 422
        assert calls["count"] == 0

    get_settings.cache_clear()


def test_capability_permission_is_checked_before_provider_call(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    calls = {"count": 0}

    async def fake_generate(self, request):
        calls["count"] += 1
        return GenerationResponse(
            content='{"category":"other"}',
            model="fake-model",
        )

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app, capability="some_other_capability")
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "support_intent",
                "message": "Hello",
            },
        )

        assert response.status_code == 403
        assert calls["count"] == 0

    get_settings.cache_clear()


def test_invalid_model_output_is_not_returned_as_success(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)

    async def fake_generate(self, request):
        return GenerationResponse(
            content='{"category":"made_up"}',
            model="fake-model",
        )

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app)
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "support_intent",
                "message": "Hello",
            },
        )

        assert response.status_code == 502
        assert "made_up" not in response.text

    get_settings.cache_clear()


def test_provider_failure_is_normalized(
    monkeypatch,
    tmp_path,
):
    from app.infrastructure.providers.ollama import ProviderUnavailableError

    _configure(monkeypatch, tmp_path)

    async def fake_generate(self, request):
        raise ProviderUnavailableError("private provider detail")

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app)
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "support_intent",
                "message": "Hello",
            },
        )

        assert response.status_code == 503
        assert "private provider detail" not in response.text

    get_settings.cache_clear()


def test_extra_request_fields_are_rejected(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    app = create_app()

    with TestClient(app) as client:
        plaintext = _create_key(app)
        response = client.post(
            "/ai/classify",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={
                "capability": "support_intent",
                "message": "Hello",
                "model": "client-selected-model",
                "provider_url": "http://127.0.0.1:11434",
            },
        )

        assert response.status_code == 422

    get_settings.cache_clear()
