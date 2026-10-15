import argparse
import sys

from app.ai.capabilities import CapabilityRegistry
from app.application.api_key_service import ApiKeyService
from app.configuration.settings import get_settings
from app.domain.exceptions import (
    ApiKeyAlreadyRevokedError,
    ApiKeyNotFoundError,
)
from app.infrastructure.persistence.api_key_repository import (
    SqliteApiKeyRepository,
)
from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.security_event_repository import (
    SqliteSecurityEventRepository,
)
from app.security.api_keys import ApiKeyManager


def build_service() -> ApiKeyService:
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()

    return ApiKeyService(
        SqliteApiKeyRepository(database),
        SqliteSecurityEventRepository(database),
        ApiKeyManager(settings.api_key_pepper),
    )


def build_parser() -> argparse.ArgumentParser:
    registry = CapabilityRegistry()

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
    create.add_argument("--client-name", required=True)
    create.add_argument(
        "--capability",
        action="append",
        choices=list(registry.ids()),
        required=True,
        help="Repeat to grant multiple registered capabilities.",
    )
    create.add_argument("--expires-in-days", type=int)

    subcommands.add_parser(
        "list-keys",
        help="List API-key metadata without secrets",
    )

    for command_name in (
        "deactivate-key",
        "activate-key",
        "revoke-key",
    ):
        command = subcommands.add_parser(command_name)
        command.add_argument("--key-id", required=True)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = build_service()

    try:
        if args.command == "create-key":
            api_key, plaintext = service.create(
                client_name=args.client_name,
                capabilities=frozenset(args.capability),
                expires_in_days=args.expires_in_days,
            )

            print(f"Key ID: {api_key.key_id}")
            print(f"Client: {api_key.client_name}")
            print("Capabilities: " + ", ".join(sorted(api_key.capabilities)))
            print(
                "Expires: "
                + (api_key.expires_at.isoformat() if api_key.expires_at else "never")
            )
            print()
            print("API key (displayed once):")
            print(plaintext)
            return

        if args.command == "list-keys":
            for api_key in service.list():
                expiration = (
                    api_key.expires_at.isoformat() if api_key.expires_at else "never"
                )
                print(
                    "\t".join(
                        [
                            api_key.key_id,
                            api_key.client_name,
                            api_key.status.value,
                            ",".join(sorted(api_key.capabilities)),
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
        result = operations[args.command](args.key_id)
        print(f"{result.key_id}: {result.status.value}")

    except (
        ApiKeyNotFoundError,
        ApiKeyAlreadyRevokedError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
