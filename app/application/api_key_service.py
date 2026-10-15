from datetime import UTC, datetime, timedelta

from app.domain.exceptions import ApiKeyNotFoundError
from app.domain.models import ApiKey, ApiKeyStatus, Capability
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import ApiKeyManager, build_api_key


def _capability_id(value: str | Capability) -> str:
    return value.value if isinstance(value, Capability) else str(value)


class ApiKeyService:
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
        capabilities: frozenset[str | Capability],
        expires_in_days: int | None = None,
    ) -> tuple[ApiKey, str]:
        normalized_name = client_name.strip()
        if not normalized_name:
            raise ValueError("client name cannot be empty")
        if len(normalized_name) > 200:
            raise ValueError("client name cannot exceed 200 characters")
        if not capabilities:
            raise ValueError("at least one capability is required")
        if expires_in_days is not None and expires_in_days <= 0:
            raise ValueError("expiration must be positive")

        capability_ids = frozenset(_capability_id(item) for item in capabilities)
        if any(not item or len(item) > 100 for item in capability_ids):
            raise ValueError("capability IDs must contain 1 to 100 characters")

        key_id, plaintext, digest = self._manager.generate()
        expires_at = (
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        )

        api_key = build_api_key(
            key_id=key_id,
            client_name=normalized_name,
            digest=digest,
            capabilities=capability_ids,
            expires_at=expires_at,
        )
        self._repository.create(api_key)

        self._record_event(
            "api_key_created",
            key_id,
            {
                "client_name": normalized_name,
                "capabilities": ",".join(sorted(capability_ids)),
            },
        )
        return api_key, plaintext

    def validate(self, plaintext: str) -> ApiKey | None:
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
        if not self._manager.verify_secret(secret, api_key.secret_digest):
            return None

        self._repository.update_last_used(key_id, now)

        updated_api_key = self._repository.get(key_id)
        if updated_api_key is None:
            return None

        return updated_api_key

    def deactivate(self, key_id: str) -> ApiKey:
        result = self._repository.set_status(key_id, ApiKeyStatus.INACTIVE)
        self._record_event("api_key_deactivated", key_id, {})
        return result

    def activate(self, key_id: str) -> ApiKey:
        result = self._repository.set_status(key_id, ApiKeyStatus.ACTIVE)
        self._record_event("api_key_activated", key_id, {})
        return result

    def revoke(self, key_id: str) -> ApiKey:
        result = self._repository.set_status(key_id, ApiKeyStatus.REVOKED)
        self._record_event("api_key_revoked", key_id, {})
        return result

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
        from app.domain.models import SecurityEvent

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
            # Do not log secrets or customer content.
            import logging

            logging.getLogger(__name__).exception(
                "security_audit_write_failed event_type=%s key_id=%s",
                event_type,
                key_id,
            )
