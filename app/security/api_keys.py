import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from app.domain.models import ApiKey, ApiKeyStatus, Capability


class ApiKeyManager:
    """
    Generates, parses, and cryptographically verifies service API keys.

    A key is represented externally as:

        agw_<key-id>_<secret>

    The key ID is not considered secret.

    Only a digest derived from the secret is persisted.
    """

    PREFIX = "agw"

    def __init__(self, pepper: str) -> None:
        self._pepper = pepper.encode("utf-8")

    def generate(self) -> tuple[str, str, bytes]:
        """
        Generate:

        1. key ID
        2. plaintext API key
        3. secure digest for persistence

        The plaintext value must only be shown at initial creation.
        """
        key_id = secrets.token_urlsafe(9)
        secret = secrets.token_urlsafe(32)

        plaintext = f"{self.PREFIX}_{key_id}_{secret}"

        digest = self._digest(secret)

        return key_id, plaintext, digest

    def digest_secret(self, secret: str) -> bytes:
        """
        Derive the persistence digest for a secret.

        This method is useful for authentication implementations and tests.
        """
        return self._digest(secret)

    def verify_secret(
        self,
        secret: str,
        expected_digest: bytes,
    ) -> bool:
        """
        Verify a secret using constant-time digest comparison.
        """
        actual_digest = self._digest(secret)

        return hmac.compare_digest(
            actual_digest,
            expected_digest,
        )

    def parse(
        self,
        plaintext: str,
    ) -> tuple[str, str] | None:
        """
        Parse an externally supplied gateway API key.

        Returns:

            (key_id, secret)

        or None when the structure is invalid.
        """
        if not isinstance(plaintext, str):
            return None

        parts = plaintext.split("_", 2)

        if len(parts) != 3:
            return None

        prefix, key_id, secret = parts

        if prefix != self.PREFIX:
            return None

        if not key_id or not secret:
            return None

        return key_id, secret

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _digest(self, secret: str) -> bytes:
        """
        Produce a keyed application-level digest.

        SHA-256 is suitable here because the secret itself has high entropy and
        is generated randomly rather than being a human-chosen password.
        """
        return hashlib.sha256(
            self._pepper + secret.encode("utf-8")
        ).digest()


def build_api_key(
    *,
    key_id: str,
    client_name: str,
    digest: bytes,
    capabilities: frozenset[Capability],
    expires_at: datetime | None,
) -> ApiKey:
    """
    Construct a new active API-key domain object.
    """
    return ApiKey(
        key_id=key_id,
        client_name=client_name,
        secret_digest=digest,
        status=ApiKeyStatus.ACTIVE,
        capabilities=capabilities,
        created_at=ApiKeyManager.utc_now(),
        last_used_at=None,
        expires_at=expires_at,
    )