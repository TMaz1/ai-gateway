import asyncio
import time
from datetime import UTC

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.configuration.settings import get_settings
from app.domain.models import Capability
from app.main import create_app
from app.security.concurrency import ConcurrencyLimiter
from app.security.dependencies import (
    require_api_key,
    require_capability,
    require_concurrency_slot,
)
from app.security.rate_limiter import InMemoryRateLimiter


def _configure(monkeypatch, tmp_path, **overrides):
    values = {
        "GATEWAY_DATABASE_PATH": str(tmp_path / "gateway.db"),
        "GATEWAY_API_KEY_PEPPER": "a-secure-test-pepper-value",
        "GATEWAY_ENVIRONMENT": "test",
        "GATEWAY_RATE_LIMIT_REQUESTS": "10",
        "GATEWAY_MAX_REQUEST_BODY_BYTES": "16",
    }
    values.update(overrides)

    for key, value in values.items():
        monkeypatch.setenv(key, value)

    get_settings.cache_clear()


def _app_with_probe_routes():
    app = create_app()
    invoked = {"count": 0}

    @app.get("/test/secure")
    async def secure(
        key=Depends(require_capability(Capability.CLASSIFICATION)),  # noqa: B008
    ):
        invoked["count"] += 1
        return {"client": key.client_name}

    @app.get("/test/forbidden")
    async def forbidden(
        key=Depends(require_capability("payments.refund")),  # noqa: B008
    ):
        invoked["count"] += 1
        return {"client": key.client_name}

    @app.get("/test/auth-only")
    async def auth_only(key=Depends(require_api_key)):
        return {"client": key.client_name}

    @app.get("/test/concurrent")
    async def concurrent(key=Depends(require_concurrency_slot())):  # noqa: B008
        await asyncio.sleep(0.15)
        return {"client": key.client_name}

    @app.post("/test/body")
    async def body_probe(payload: dict):
        invoked["count"] += 1
        return payload

    return app, invoked


def test_authentication_requires_valid_bearer_key(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app, _ = _app_with_probe_routes()

    with TestClient(app) as client:
        assert client.get("/test/secure").status_code == 401

        invalid = client.get(
            "/test/secure",
            headers={"Authorization": "Bearer nonsense"},
        )
        assert invalid.status_code == 401

        _, plaintext = app.state.api_key_service.create(
            client_name="test-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )

        response = client.get(
            "/test/secure",
            headers={"Authorization": f"Bearer {plaintext}"},
        )

        assert response.status_code == 200
        assert response.json() == {"client": "test-client"}
        assert response.headers["X-Request-ID"]

    get_settings.cache_clear()


def test_missing_capability_is_denied_before_endpoint_runs(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    app, invoked = _app_with_probe_routes()

    with TestClient(app) as client:
        _, plaintext = app.state.api_key_service.create(
            client_name="classification-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )

        response = client.get(
            "/test/forbidden",
            headers={"Authorization": f"Bearer {plaintext}"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert invoked["count"] == 0

    get_settings.cache_clear()


def test_rate_limiter_enforces_window_boundary_and_bounds_state():
    limiter = InMemoryRateLimiter(
        limit=2,
        window_seconds=10,
        max_tracked_keys=2,
    )

    assert limiter.check("a", now=1).allowed
    assert limiter.check("a", now=2).allowed

    blocked = limiter.check("a", now=3)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 7

    assert limiter.check("b", now=3).allowed
    assert not limiter.check("c", now=3).allowed
    assert limiter.check("c", now=10).allowed


def test_rate_limit_is_enforced_at_authentication_boundary(
    monkeypatch,
    tmp_path,
):
    _configure(
        monkeypatch,
        tmp_path,
        GATEWAY_RATE_LIMIT_REQUESTS="1",
    )
    app, _ = _app_with_probe_routes()

    with TestClient(app) as client:
        _, plaintext = app.state.api_key_service.create(
            client_name="limited-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )
        headers = {"Authorization": f"Bearer {plaintext}"}

        assert client.get("/test/auth-only", headers=headers).status_code == 200

        response = client.get("/test/secure", headers=headers)
        assert response.status_code == 429
        assert response.headers["Retry-After"]
        assert response.json()["error"]["code"] == "RATE_LIMITED"

    get_settings.cache_clear()


def test_concurrency_limits_and_idempotent_release():
    async def run():
        limiter = ConcurrencyLimiter(global_limit=2, per_key_limit=1)

        first = await limiter.try_acquire("key-a")
        assert first is not None
        assert await limiter.try_acquire("key-a") is None

        second = await limiter.try_acquire("key-b")
        assert second is not None
        assert await limiter.try_acquire("key-c") is None

        await first.release()
        await first.release()

        third = await limiter.try_acquire("key-c")
        assert third is not None

        await second.release()
        await third.release()

        active, by_key = await limiter.snapshot()
        assert active == 0
        assert by_key == {}

    asyncio.run(run())


def test_concurrency_lease_releases_when_task_is_cancelled():
    async def run():
        limiter = ConcurrencyLimiter(global_limit=1, per_key_limit=1)
        started = asyncio.Event()

        async def worker():
            lease = await limiter.try_acquire("key-a")
            assert lease is not None

            async with lease:
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(worker())
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        active, by_key = await limiter.snapshot()
        assert active == 0
        assert by_key == {}

    asyncio.run(run())


def test_body_size_and_media_type_are_rejected_before_route(
    monkeypatch,
    tmp_path,
):
    _configure(
        monkeypatch,
        tmp_path,
        GATEWAY_MAX_REQUEST_BODY_BYTES="8",
    )
    app, invoked = _app_with_probe_routes()

    with TestClient(app) as client:
        oversized = client.post(
            "/test/body",
            content=b'{"value":"long"}',
            headers={"Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "REQUEST_TOO_LARGE"

        wrong_type = client.post(
            "/test/body",
            content=b'{"a":1}',
            headers={"Content-Type": "text/plain"},
        )
        assert wrong_type.status_code == 415
        assert wrong_type.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

        assert invoked["count"] == 0
        assert oversized.headers["X-Request-ID"]

    get_settings.cache_clear()


def test_validation_and_internal_errors_are_safe(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app()

    @app.get("/test/boom")
    async def boom():
        raise RuntimeError("secret database path /private/path")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/boom")

        assert response.status_code == 500
        assert "private/path" not in response.text
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert response.headers["X-Request-ID"]

    get_settings.cache_clear()


def test_inactive_and_revoked_keys_cannot_authenticate(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    app, _ = _app_with_probe_routes()

    with TestClient(app) as client:
        service = app.state.api_key_service

        inactive, inactive_plaintext = service.create(
            client_name="inactive-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )
        service.deactivate(inactive.key_id)

        revoked, revoked_plaintext = service.create(
            client_name="revoked-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )
        service.revoke(revoked.key_id)

        for plaintext in (inactive_plaintext, revoked_plaintext):
            response = client.get(
                "/test/auth-only",
                headers={"Authorization": f"Bearer {plaintext}"},
            )
            assert response.status_code == 401

    get_settings.cache_clear()


def test_expired_key_cannot_authenticate(monkeypatch, tmp_path):
    from datetime import datetime, timedelta

    _configure(monkeypatch, tmp_path)
    app, _ = _app_with_probe_routes()

    with TestClient(app) as client:
        service = app.state.api_key_service
        created, plaintext = service.create(
            client_name="expired-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )

        with app.state.database.connection() as connection:
            connection.execute(
                "UPDATE api_keys SET expires_at = ? WHERE key_id = ?",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    created.key_id,
                ),
            )

        response = client.get(
            "/test/auth-only",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401

    get_settings.cache_clear()


def test_concurrency_dependency_rejects_over_limit_and_releases_lease(
    monkeypatch,
    tmp_path,
):
    _configure(
        monkeypatch,
        tmp_path,
        GATEWAY_MAX_CONCURRENT_GLOBAL="1",
        GATEWAY_MAX_CONCURRENT_PER_KEY="1",
    )
    app, _ = _app_with_probe_routes()

    with TestClient(app) as client:
        _, plaintext = app.state.api_key_service.create(
            client_name="concurrent-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        results = []

        def request_once():
            results.append(client.get("/test/concurrent", headers=headers))

        import threading

        first = threading.Thread(target=request_once)
        first.start()
        time.sleep(0.04)

        second = client.get("/test/concurrent", headers=headers)
        first.join()

        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMITED" or (
            second.json()["error"]["code"] == "CONCURRENCY_LIMITED"
        )
        assert results[0].status_code == 200

        active, by_key = asyncio.run(app.state.concurrency_limiter.snapshot())
        assert active == 0
        assert by_key == {}

    get_settings.cache_clear()


def test_create_app_does_not_initialize_database_until_startup(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "not-yet-created.db"
    _configure(
        monkeypatch,
        tmp_path,
        GATEWAY_DATABASE_PATH=str(database_path),
    )

    app = create_app()
    assert not database_path.exists()

    with TestClient(app):
        assert database_path.exists()

    get_settings.cache_clear()


def test_malformed_json_uses_normalized_validation_error(
    monkeypatch,
    tmp_path,
):
    _configure(monkeypatch, tmp_path)
    app, invoked = _app_with_probe_routes()

    with TestClient(app) as client:
        response = client.post(
            "/test/body",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert invoked["count"] == 0

    get_settings.cache_clear()


def test_api_key_lifecycle_writes_audit_events_without_plaintext_secret(
    monkeypatch,
    tmp_path,
):
    import json

    _configure(monkeypatch, tmp_path)
    app, _ = _app_with_probe_routes()

    with TestClient(app):
        service = app.state.api_key_service

        created, plaintext = service.create(
            client_name="audited-client",
            capabilities=frozenset({Capability.CLASSIFICATION}),
        )
        service.deactivate(created.key_id)
        service.activate(created.key_id)
        service.revoke(created.key_id)

        with app.state.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT event_type, metadata_json
                FROM security_events
                WHERE key_id = ?
                ORDER BY id
                """,
                (created.key_id,),
            ).fetchall()

        assert [row["event_type"] for row in rows] == [
            "api_key_created",
            "api_key_deactivated",
            "api_key_activated",
            "api_key_revoked",
        ]
        assert all(plaintext not in row["metadata_json"] for row in rows)
        assert all(isinstance(json.loads(row["metadata_json"]), dict) for row in rows)

    get_settings.cache_clear()
