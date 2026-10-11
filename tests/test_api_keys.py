from datetime import UTC, datetime, timedelta

from app.domain.models import ApiKey, ApiKeyStatus, Capability
from app.security.api_keys import ApiKeyManager


def test_generated_key_can_be_verified():
    manager = ApiKeyManager("a-secure-development-pepper")

    key_id, plaintext, digest = manager.generate()
    parsed = manager.parse(plaintext)

    assert parsed is not None

    parsed_key_id, secret = parsed
    assert parsed_key_id == key_id
    assert manager.verify_secret(secret, digest)


def test_wrong_secret_does_not_verify():
    manager = ApiKeyManager("a-secure-development-pepper")
    _, _, digest = manager.generate()

    assert not manager.verify_secret("wrong-secret", digest)


def test_different_peppers_produce_different_digests():
    manager_a = ApiKeyManager("first-development-pepper")
    manager_b = ApiKeyManager("second-development-pepper")
    secret = "same-secret"

    digest_a = manager_a.digest_secret(secret)
    digest_b = manager_b.digest_secret(secret)

    assert digest_a != digest_b


def test_key_format_rejects_malformed_values():
    manager = ApiKeyManager("a-secure-development-pepper")

    assert manager.parse("not-a-key") is None
    assert manager.parse("agw_only-two-parts") is None
    assert manager.parse("wrong_prefix_key_secret") is None


def test_key_expiration_is_enforced():
    expired = ApiKey(
        key_id="key",
        client_name="client",
        secret_digest=b"digest",
        status=ApiKeyStatus.ACTIVE,
        capabilities=frozenset({Capability.CLASSIFICATION}),
        created_at=datetime.now(UTC) - timedelta(days=2),
        last_used_at=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert not expired.is_usable(datetime.now(UTC))


def test_inactive_key_is_not_usable():
    inactive = ApiKey(
        key_id="key",
        client_name="client",
        secret_digest=b"digest",
        status=ApiKeyStatus.INACTIVE,
        capabilities=frozenset({Capability.CLASSIFICATION}),
        created_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=None,
    )

    assert not inactive.is_usable(datetime.now(UTC))


def test_revoked_key_is_not_usable():
    revoked = ApiKey(
        key_id="key",
        client_name="client",
        secret_digest=b"digest",
        status=ApiKeyStatus.REVOKED,
        capabilities=frozenset({Capability.CLASSIFICATION}),
        created_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=None,
    )

    assert not revoked.is_usable(datetime.now(UTC))


def test_parser_preserves_unambiguous_legacy_key_ids():
    manager = ApiKeyManager("a-secure-development-pepper")

    parsed = manager.parse("agw_legacy-id_" + "a" * 43)

    assert parsed == ("legacy-id", "a" * 43)
