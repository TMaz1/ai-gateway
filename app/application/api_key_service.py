from datetime import datetime, timedelta, timezone

from app.domain.exceptions import ApiKeyNotFoundError
from app.domain.models import ApiKey, ApiKeyStatus, Capability
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import (
    ApiKeyManager,
    build_api_key,
)


class ApiKeyService:
    """
    Application service for API-key lifecycle management.

    This service coordinates cryptographic key handling and persistence while
    keeping HTTP concerns out of the application layer.
    """

    def __init__(
        self,
        repository: SqliteApiKeyRepository,
        events: SqliteSecurityEventRepository,
        manager: ApiKeyManager,
    ) -> None:
        self._repository = repository
        self._events = events
        self._manager = manager

    def create(
        self,
        *,
        client_name: str,
        capabilities: frozenset[Capability],
        expires_in_days: int | None = None,
    ) -> tuple[ApiKey, str]:
        """
        Create an API key.

        Returns the domain record and plaintext secret.

        The plaintext secret is intentionally returned from this creation
        operation only. Normal retrieval/list operations never expose it.
        """
        normalized_client_name = client_name.strip()

        if not normalized_client_name:
            raise ValueError(
                "client name cannot be empty"
            )

        if len(normalized_client_name) > 200:
            raise ValueError(
                "client name cannot exceed 200 characters"
            )

        if not capabilities:
            raise ValueError(
                "at least one capability is required"
            )

        if expires_in_days is not None and expires_in_days <= 0:
            raise ValueError(
                "expiration must be positive"
            )

        key_id, plaintext, digest = self._manager.generate()

        expires_at = None

        if expires_in_days is not None:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(days=expires_in_days)
            )

        api_key = build_api_key(
            key_id=key_id,
            client_name=normalized_client_name,
            digest=digest,
            capabilities=capabilities,
            expires_at=expires_at,
        )

        self._repository.create(api_key)

        return api_key, plaintext

    def validate(
        self,
        plaintext: str,
    ) -> ApiKey | None:
        """
        Validate a supplied API key.

        Invalid, inactive, revoked, expired, malformed, and unknown keys all
        return None. This avoids exposing key-state information through the
        authentication primitive.
        """
        parsed = self._manager.parse(plaintext)

        if parsed is None:
            return None

        key_id, secret = parsed

        api_key = self._repository.get(key_id)

        if api_key is None:
            return None

        now = datetime.now(timezone.utc)

        if not api_key.is_usable(now):
            return None

        if not self._manager.verify_secret(
            secret,
            api_key.secret_digest,
        ):
            return None

        self._repository.update_last_used(key_id, now)

        return api_key

    def deactivate(self, key_id: str) -> ApiKey:
        return self._repository.set_status(
            key_id,
            ApiKeyStatus.INACTIVE,
        )

    def activate(self, key_id: str) -> ApiKey:
        return self._repository.set_status(
            key_id,
            ApiKeyStatus.ACTIVE,
        )

    def revoke(self, key_id: str) -> ApiKey:
        return self._repository.set_status(
            key_id,
            ApiKeyStatus.REVOKED,
        )

    def get(self, key_id: str) -> ApiKey:
        api_key = self._repository.get(key_id)

        if api_key is None:
            raise ApiKeyNotFoundError(key_id)

        return api_key

    def list(self) -> list[ApiKey]:
        return self._repository.list()