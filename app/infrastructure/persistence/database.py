import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    """
    Small SQLite infrastructure wrapper.

    The rest of the application does not need to know how SQLite connections
    are created or how the schema is initialized.
    """

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        """
        Create the database directory and schema if required.
        """
        path = Path(self.database_path)

        if self.database_path != ":memory:":
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    secret_digest BLOB NOT NULL,
                    status TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    expires_at TEXT
                );

                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    key_id TEXT,
                    request_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_api_keys_status
                    ON api_keys(status);

                CREATE INDEX IF NOT EXISTS idx_security_events_created_at
                    ON security_events(created_at);

                CREATE INDEX IF NOT EXISTS idx_security_events_key_id
                    ON security_events(key_id);
                """
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """
        Provide a transaction-scoped SQLite connection.

        Queries in repositories are parameterized and therefore do not accept
        arbitrary SQL from callers.
        """
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
        )

        connection.row_factory = sqlite3.Row

        try:
            yield connection
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()