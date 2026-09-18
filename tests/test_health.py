from fastapi.testclient import TestClient

from app.configuration.settings import get_settings
from app.main import create_app


def test_health_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GATEWAY_DATABASE_PATH",
        str(tmp_path / "gateway.db"),
    )

    monkeypatch.setenv(
        "GATEWAY_API_KEY_PEPPER",
        "a-secure-development-pepper",
    )

    monkeypatch.setenv(
        "GATEWAY_ENVIRONMENT",
        "test",
    )

    get_settings.cache_clear()

    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/health"
        )

        assert response.status_code == 200

        assert response.json() == {
            "status": "ok",
        }

        assert response.headers.get(
            "X-Request-ID"
        )

        ready = client.get(
            "/health/ready"
        )

        assert ready.status_code == 200

        assert ready.json() == {
            "status": "ready",
        }

        assert ready.headers.get(
            "X-Request-ID"
        )

    get_settings.cache_clear()


def test_invalid_incoming_request_id_is_replaced(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "GATEWAY_DATABASE_PATH",
        str(tmp_path / "gateway.db"),
    )

    monkeypatch.setenv(
        "GATEWAY_API_KEY_PEPPER",
        "a-secure-development-pepper",
    )

    monkeypatch.setenv(
        "GATEWAY_ENVIRONMENT",
        "test",
    )

    get_settings.cache_clear()

    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={
                "X-Request-ID": (
                    "malicious value with spaces"
                )
            },
        )

        assert response.status_code == 200

        returned_id = response.headers[
            "X-Request-ID"
        ]

        assert returned_id != (
            "malicious value with spaces"
        )

        assert len(returned_id) == 32

    get_settings.cache_clear()


def test_valid_request_id_is_preserved(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "GATEWAY_DATABASE_PATH",
        str(tmp_path / "gateway.db"),
    )

    monkeypatch.setenv(
        "GATEWAY_API_KEY_PEPPER",
        "a-secure-development-pepper",
    )

    monkeypatch.setenv(
        "GATEWAY_ENVIRONMENT",
        "test",
    )

    get_settings.cache_clear()

    app = create_app()

    request_id = "client-request-123"

    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={
                "X-Request-ID": request_id,
            },
        )

        assert response.status_code == 200
        assert response.headers[
            "X-Request-ID"
        ] == request_id

    get_settings.cache_clear()