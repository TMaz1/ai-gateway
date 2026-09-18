import argparse
import sys

from app.application.api_key_service import ApiKeyService
from app.configuration.settings import get_settings
from app.domain.exceptions import (
    ApiKeyAlreadyRevokedError,
    ApiKeyNotFoundError,
)
from app.domain.models import Capability
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import ApiKeyManager


def build_service() -> ApiKeyService:
    """
    Build the API-key application service using the configured SQLite store.
    """
    settings = get_settings()

    database = Database(
        settings.database_path
    )

    database.initialize()

    repository = SqliteApiKeyRepository(
        database
    )

    events = SqliteSecurityEventRepository(
        database
    )

    manager = ApiKeyManager(
        settings.api_key_pepper
    )

    return ApiKeyService(
        repository,
        events,
        manager,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Gateway local administration CLI",
    )

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = subcommands.add_parser(
        "create-key",
        help="Create a service API key",
    )

    create.add_argument(
        "--client-name",
        required=True,
    )

    create.add_argument(
        "--capability",
        action="append",
        choices=[
            capability.value
            for capability in Capability
        ],
        required=True,
    )

    create.add_argument(
        "--expires-in-days",
        type=int,
    )

    subcommands.add_parser(
        "list-keys",
        help="List API-key metadata without secrets",
    )

    for command_name in (
        "deactivate-key",
        "activate-key",
        "revoke-key",
    ):
        command = subcommands.add_parser(
            command_name,
        )

        command.add_argument(
            "--key-id",
            required=True,
        )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    service = build_service()

    try:
        if args.command == "create-key":
            api_key, plaintext = service.create(
                client_name=args.client_name,
                capabilities=frozenset(
                    Capability(item)
                    for item in args.capability
                ),
                expires_in_days=args.expires_in_days,
            )

            print(
                f"Key ID: {api_key.key_id}"
            )

            print(
                f"Client: {api_key.client_name}"
            )

            print(
                "Capabilities: "
                + ", ".join(
                    sorted(
                        capability.value
                        for capability in api_key.capabilities
                    )
                )
            )

            if api_key.expires_at:
                print(
                    "Expires: "
                    + api_key.expires_at.isoformat()
                )
            else:
                print("Expires: never")

            print()
            print(
                "API key (displayed once):"
            )
            print(plaintext)

            return

        if args.command == "list-keys":
            for api_key in service.list():
                expiration = (
                    api_key.expires_at.isoformat()
                    if api_key.expires_at
                    else "never"
                )

                capabilities = ",".join(
                    sorted(
                        capability.value
                        for capability in api_key.capabilities
                    )
                )

                print(
                    "\t".join(
                        [
                            api_key.key_id,
                            api_key.client_name,
                            api_key.status.value,
                            capabilities,
                            expiration,
                        ]
                    )
                )

            return

        operations = {
            "deactivate-key": service.deactivate,
            "activate-key": service.activate,
            "revoke-key": service.revoke,
        }

        operation = operations[args.command]

        result = operation(
            args.key_id
        )

        print(
            f"{result.key_id}: {result.status.value}"
        )

    except (
        ApiKeyNotFoundError,
        ApiKeyAlreadyRevokedError,
        ValueError,
    ) as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()