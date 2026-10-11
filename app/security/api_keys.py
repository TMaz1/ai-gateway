import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime

from app.domain.models import ApiKey

_KEY_PATTERN = re.compile(
    r"^agw_([A-Za-z0-9-]{1,32})_([A-Za-z0-9_-]{32,})$"
)  # agw (identifies the key format), public key identifier, then secret that proves possession of the key, with "_" separator


class ApiKeyManager:
    """Generate and verify service API keys without persisting plaintext secrets."""

    PREFIX = "agw"

    def __init__(self, pepper: str) -> None:
        if len(pepper) < 16:
            raise ValueError("API-key pepper must be at least 16 characters")
        self._pepper = pepper.encode("utf-8")

    def generate(self) -> tuple[str, str, bytes]:
        # Hex IDs cannot contain the delimiter used by the external key format.
        key_id = secrets.token_hex(9)
        secret = secrets.token_urlsafe(32)
        plaintext = f"{self.PREFIX}_{key_id}_{secret}"
        return key_id, plaintext, self._digest(secret)

    def digest_secret(self, secret: str) -> bytes:
        return self._digest(secret)

    def verify_secret(self, secret: str, expected_digest: bytes) -> bool:
        return hmac.compare_digest(self._digest(secret), expected_digest)

    def parse(self, plaintext: str) -> tuple[str, str] | None:
        if not isinstance(plaintext, str) or len(plaintext) > 256:
            return None

        match = _KEY_PATTERN.fullmatch(plaintext)
        if match is None:
            return None

        return match.group(1), match.group(2)

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)

    def _digest(self, secret: str) -> bytes:
        return hmac.new(
            self._pepper,
            secret.encode("utf-8"),
            hashlib.sha256,
        ).digest()


def build_api_key(
    *,
    key_id,
    client_name,
    digest,
    capabilities,
    expires_at=None,
) -> ApiKey:
    from app.domain.models import ApiKeyStatus

    return ApiKey(
        key_id=key_id,
        client_name=client_name,
        secret_digest=digest,
        status=ApiKeyStatus.ACTIVE,
        capabilities=frozenset(capabilities),
        created_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=expires_at,
    )
