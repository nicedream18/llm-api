"""Local-only entry points; importing this module never starts services or edits files."""

import argparse
import json
import sys
from pathlib import Path

from app.local_config import TARGETS, ClientConfigurations


def main(argv=None):
    parser = argparse.ArgumentParser(description="WaLiAPI explicit local client and service management")
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config"); config.add_argument("operation", choices=("detect", "preview", "export", "apply", "restore"))
    config.add_argument("--home", type=Path); config.add_argument("--target", choices=tuple(TARGETS))
    config.add_argument("--url", default="http://127.0.0.1:9900"); config.add_argument("--allow-remote", action="store_true")
    config.add_argument("--expected-sha256"); config.add_argument("--backup-id")
    service = commands.add_parser("service"); service.add_argument("operation", choices=("start", "status", "stop")); service.add_argument("--state-dir", type=Path); service.add_argument("--port", type=int, default=9900)
    bridge_parser = commands.add_parser("bridge"); bridge_parser.add_argument("--url", default="http://127.0.0.1:9900"); bridge_parser.add_argument("--allow-remote", action="store_true")
    rotation = commands.add_parser("rotate-provider-keys"); rotation.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "config":
            manager = ClientConfigurations(args.home)
            if args.operation == "detect": result = manager.detect()
            else:
                if not args.target: parser.error("--target is required")
                if args.operation == "restore":
                    if not args.backup_id: parser.error("--backup-id is required")
                    result = manager.restore(args.target, args.backup_id)
                elif args.operation == "apply":
                    if not args.expected_sha256: parser.error("--expected-sha256 from preview is required")
                    result = manager.apply(args.target, args.expected_sha256, args.url, args.allow_remote)
                else: result = manager.preview(args.target, args.url, args.allow_remote)
        elif args.command == "service":
            from app.local_service import ManagedService
            manager_service = ManagedService(args.state_dir)
            result = manager_service.start(args.port) if args.operation == "start" else getattr(manager_service, args.operation)()
        elif args.command == "bridge":
            from app.local_bridge import bridge
            bridge(sys.stdin, sys.stdout, args.url, args.allow_remote)
            return 0
        else:
            from app.application.services.provider_service import ProviderService
            from app.infrastructure.repositories.provider_repo import ProviderRepository
            from app.infrastructure.token_keyring import rotate_provider_storage
            result = rotate_provider_storage(ProviderRepository(), ProviderService._cipher())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:  # noqa: BLE001 - CLI boundary must not print decoder contents or credentials
        # Library/decoder errors can contain file contents and credentials.
        print(json.dumps({"error": "Local operation failed; check permissions, input, file changes and environment references"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
