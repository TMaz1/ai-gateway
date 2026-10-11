import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.domain.exceptions import ApiKeyNotFoundError
from app.domain.models import (
    ApiKey,
    ApiKeyStatus,
    Capability,
    SecurityEvent,
)
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import ApiKeyManager, build_api_key

logger = logging.getLogger(__name__)


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

        Returns the domain record and plaintext secret. The plaintext secret
        is intentionally returned only by this creation operation.
        """
        normalized_client_name = client_name.strip()

        if not normalized_client_name:
            raise ValueError("client name cannot be empty")

        if len(normalized_client_name) > 200:
            raise ValueError("client name cannot exceed 200 characters")

        if not capabilities:
            raise ValueError("at least one capability is required")

        if expires_in_days is not None and expires_in_days <= 0:
            raise ValueError("expiration must be positive")

        key_id, plaintext, digest = self._manager.generate()

        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        api_key = build_api_key(
            key_id=key_id,
            client_name=normalized_client_name,
            digest=digest,
            capabilities=capabilities,
            expires_at=expires_at,
        )

        self._repository.create(api_key)
        self._record_event(
            "api_key_created",
            api_key.key_id,
            {
                "client_name": normalized_client_name,
                "capabilities": ",".join(sorted(item.value for item in capabilities)),
            },
        )

        return api_key, plaintext

    def validate(self, plaintext: str) -> ApiKey | None:
        """
        Validate a supplied API key.

        Invalid, inactive, revoked, expired, malformed, and unknown keys all
        return None, avoiding disclosure of key state through authentication.
        """
        parsed = self._manager.parse(plaintext)
        if parsed is None:
            return None

        key_id, secret = parsed
        api_key = self._repository.get(key_id)

        if api_key is None:
            return None

        now = datetime.now(UTC)
        if not api_key.is_usable(now):
            return None

        if not self._manager.verify_secret(
            secret,
            api_key.secret_digest,
        ):
            return None

        self._repository.update_last_used(key_id, now)

        # Return an object reflecting the last-used timestamp just persisted.
        return replace(api_key, last_used_at=now)

    def deactivate(self, key_id: str) -> ApiKey:
        api_key = self._repository.set_status(
            key_id,
            ApiKeyStatus.INACTIVE,
        )
        self._record_event("api_key_deactivated", key_id, {})
        return api_key

    def activate(self, key_id: str) -> ApiKey:
        api_key = self._repository.set_status(
            key_id,
            ApiKeyStatus.ACTIVE,
        )
        self._record_event("api_key_activated", key_id, {})
        return api_key

    def revoke(self, key_id: str) -> ApiKey:
        api_key = self._repository.set_status(
            key_id,
            ApiKeyStatus.REVOKED,
        )
        self._record_event("api_key_revoked", key_id, {})
        return api_key

    def get(self, key_id: str) -> ApiKey:
        api_key = self._repository.get(key_id)
        if api_key is None:
            raise ApiKeyNotFoundError(key_id)
        return api_key

    def list(self) -> list[ApiKey]:
        return self._repository.list()

    def _record_event(
        self,
        event_type: str,
        key_id: str,
        metadata: dict[str, str],
    ) -> None:
        event = SecurityEvent(
            event_type=event_type,
            key_id=key_id,
            request_id=None,
            metadata={key: str(value)[:128] for key, value in metadata.items()},
            created_at=datetime.now(UTC),
        )

        try:
            self._events.record(event)
        except Exception:
            # Preserve the primary lifecycle result; never log secrets or metadata.
            logger.exception(
                "security_audit_write_failed event_type=%s key_id=%s",
                event_type,
                key_id,
            )
