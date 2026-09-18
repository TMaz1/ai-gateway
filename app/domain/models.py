from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ApiKeyStatus(StrEnum):
    """
    Lifecycle state of a gateway API key.

    REVOKED is terminal.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


class Capability(StrEnum):
    """
    Gateway capabilities.

    The list is intentionally small in Batch 1. Additional capabilities can
    be added as corresponding gateway endpoints are designed.
    """

    CLASSIFICATION = "classification"


@dataclass(frozen=True)
class ApiKey:
    """
    Domain representation of a service API key.

    secret_digest is never the plaintext API-key secret.
    """

    key_id: str
    client_name: str
    secret_digest: bytes
    status: ApiKeyStatus
    capabilities: frozenset[Capability]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None

    def is_usable(self, now: datetime) -> bool:
        """
        Determine whether the key may authenticate a request at `now`.
        """
        if self.status is not ApiKeyStatus.ACTIVE:
            return False

        if self.expires_at is not None and self.expires_at <= now:
            return False

        return True


@dataclass(frozen=True)
class SecurityEvent:
    """
    Security/audit event.

    Metadata must never contain API-key secrets, passwords, tokens, or
    unnecessary customer content.
    """

    event_type: str
    key_id: str | None
    request_id: str | None
    metadata: dict[str, str]
    created_at: datetime