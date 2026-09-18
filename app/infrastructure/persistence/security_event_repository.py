import json

from app.domain.models import SecurityEvent
from app.infrastructure.persistence.database import Database


class SqliteSecurityEventRepository:
    """
    SQLite persistence for security/audit events.

    Security events intentionally contain metadata rather than arbitrary
    request/response bodies.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, event: SecurityEvent) -> None:
        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO security_events (
                    event_type,
                    key_id,
                    request_id,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.key_id,
                    event.request_id,
                    json.dumps(
                        event.metadata,
                        separators=(",", ":"),
                    ),
                    event.created_at.isoformat(),
                ),
            )