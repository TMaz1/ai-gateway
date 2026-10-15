import json
from datetime import UTC, datetime
from typing import Any

from app.domain.exceptions import (
    ApiKeyAlreadyRevokedError,
    ApiKeyNotFoundError,
)
from app.domain.models import ApiKey, ApiKeyStatus
from app.infrastructure.persistence.database import Database


class SqliteApiKeyRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, api_key: ApiKey) -> None:
        capabilities = json.dumps(sorted(api_key.capabilities))

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO api_keys (
                    key_id, client_name, secret_digest, status,
                    capabilities, created_at, last_used_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    api_key.key_id,
                    api_key.client_name,
                    api_key.secret_digest,
                    api_key.status.value,
                    capabilities,
                    api_key.created_at.isoformat(),
                    (
                        api_key.last_used_at.isoformat()
                        if api_key.last_used_at
                        else None
                    ),
                    (api_key.expires_at.isoformat() if api_key.expires_at else None),
                ),
            )

    def get(self, key_id: str) -> ApiKey | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT key_id, client_name, secret_digest, status,
                       capabilities, created_at, last_used_at, expires_at
                FROM api_keys WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()

        return self._row_to_model(row) if row is not None else None

    def list(self) -> list[ApiKey]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT key_id, client_name, secret_digest, status,
                       capabilities, created_at, last_used_at, expires_at
                FROM api_keys ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_model(row) for row in rows]

    def set_status(self, key_id: str, status: ApiKeyStatus) -> ApiKey:
        current = self.get(key_id)
        if current is None:
            raise ApiKeyNotFoundError(key_id)

        if (
            current.status is ApiKeyStatus.REVOKED
            and status is not ApiKeyStatus.REVOKED
        ):
            raise ApiKeyAlreadyRevokedError(key_id)

        with self._database.connection() as connection:
            connection.execute(
                "UPDATE api_keys SET status = ? WHERE key_id = ?",
                (status.value, key_id),
            )

        updated = self.get(key_id)
        if updated is None:
            raise ApiKeyNotFoundError(key_id)
        return updated

    def update_last_used(
        self,
        key_id: str,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or datetime.now(UTC)
        with self._database.connection() as connection:
            connection.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                (timestamp.isoformat(), key_id),
            )

    @staticmethod
    def _row_to_model(row: Any) -> ApiKey:
        # String capability IDs allow future registry entries without a
        # database schema change or a domain enum change.
        capabilities = frozenset(json.loads(row["capabilities"]))

        return ApiKey(
            key_id=row["key_id"],
            client_name=row["client_name"],
            secret_digest=bytes(row["secret_digest"]),
            status=ApiKeyStatus(row["status"]),
            capabilities=capabilities,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"])
                if row["last_used_at"]
                else None
            ),
            expires_at=(
                datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
            ),
        )
