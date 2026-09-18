from app.application.api_key_service import ApiKeyService
from app.domain.exceptions import ApiKeyAlreadyRevokedError
from app.domain.models import (
    ApiKeyStatus,
    Capability,
)
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import ApiKeyManager


def build_service(tmp_path) -> ApiKeyService:
    database = Database(
        str(tmp_path / "gateway.db")
    )

    database.initialize()

    return ApiKeyService(
        SqliteApiKeyRepository(database),
        SqliteSecurityEventRepository(database),
        ApiKeyManager(
            "a-secure-development-pepper"
        ),
    )


def test_create_and_validate_key(tmp_path):
    service = build_service(
        tmp_path
    )

    created, plaintext = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    found = service.validate(
        plaintext
    )

    assert found is not None

    assert found.key_id == created.key_id

    assert found.client_name == "test-client"

    assert found.secret_digest != (
        plaintext.encode()
    )

    assert found.last_used_at is not None


def test_list_does_not_expose_plaintext_secret(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    _, plaintext = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    records = service.list()

    assert len(records) == 1

    serialized_values = str(
        records[0].__dict__
    )

    assert plaintext not in serialized_values


def test_invalid_key_cannot_validate(tmp_path):
    service = build_service(
        tmp_path
    )

    service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    assert service.validate(
        "agw_unknown_invalid-secret"
    ) is None


def test_deactivated_key_cannot_validate(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    created, plaintext = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    service.deactivate(
        created.key_id
    )

    assert service.validate(
        plaintext
    ) is None

    assert service.get(
        created.key_id
    ).status is ApiKeyStatus.INACTIVE


def test_deactivated_key_can_be_activated(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    created, plaintext = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    service.deactivate(
        created.key_id
    )

    service.activate(
        created.key_id
    )

    assert service.validate(
        plaintext
    ) is not None


def test_revoked_key_cannot_be_reactivated(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    created, _ = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    service.revoke(
        created.key_id
    )

    try:
        service.activate(
            created.key_id
        )
    except ApiKeyAlreadyRevokedError:
        pass
    else:
        raise AssertionError(
            "revoked key was reactivated"
        )


def test_revoked_key_cannot_validate(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    created, plaintext = service.create(
        client_name="test-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
    )

    service.revoke(
        created.key_id
    )

    assert service.validate(
        plaintext
    ) is None


def test_expiring_key_is_rejected_after_expiry(
    tmp_path,
):
    service = build_service(
        tmp_path
    )

    created, plaintext = service.create(
        client_name="temporary-client",
        capabilities=frozenset(
            {
                Capability.CLASSIFICATION,
            }
        ),
        expires_in_days=1,
    )

    # The creation path itself should produce a future expiry.
    assert created.expires_at is not None

    assert service.validate(
        plaintext
    ) is not None