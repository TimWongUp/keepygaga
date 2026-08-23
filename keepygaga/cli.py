from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from keepygaga.config import PROJECT_ROOT, load_config, resolve_config_path
from keepygaga.diagnostics import run_doctor
from keepygaga.host_setup import (
    HostSetupError,
    HostSetupPartialError,
    setup_codex_host,
)
from keepygaga.memory import initialize_memory_tree


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keepygaga",
        description="Run a Keepygaga core-memory maintenance command.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="configuration path (overrides KEEPYGAGA_CONFIG)",
    )
    commands = parser.add_subparsers(dest="command")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_commands.add_parser("init")

    host = commands.add_parser("host")
    host_commands = host.add_subparsers(dest="host_command", required=True)
    setup = host_commands.add_parser("setup")
    setup.add_argument("host", choices=("codex",))
    setup.add_argument("--codex-home", type=Path)
    setup.add_argument("--codex-binary", type=Path)
    setup.add_argument("--hook-runtime", type=Path)
    setup.add_argument("--hook-python", type=Path)
    setup.add_argument("--hook-config", type=Path)

    return parser


def _print(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    explicit_config = args.config.expanduser().resolve() if args.config else None
    config_path = resolve_config_path(explicit_config)
    if args.command == "doctor":
        payload = run_doctor(config_path, project_root=PROJECT_ROOT)
        _print(payload)
        return 1 if payload["status"] == "error" else 0

    try:
        config = load_config(config_path)
    except Exception as exc:
        _print(
            {
                "status": "invalid_source",
                "message": f"configuration could not be loaded: {exc}",
            }
        )
        return 1
    if args.command == "memory" and args.memory_command == "init":
        if not config.memory.root.strip():
            _print(
                {
                    "status": "invalid_source",
                    "message": "memory.root is not configured",
                }
            )
            return 1
        payload = initialize_memory_tree(
            Path(config.memory.root).expanduser(), config.memory
        )
        _print(payload)
        return 0 if payload["status"] in {"applied", "no_op"} else 1

    if args.command == "host" and args.host_command == "setup":
        try:
            payload = setup_codex_host(
                config_path,
                config,
                codex_home=args.codex_home,
                codex_binary=args.codex_binary,
                hook_runtime=args.hook_runtime,
                hook_python=args.hook_python,
                hook_config_path=args.hook_config,
            )
        except HostSetupPartialError as exc:
            _print(
                {
                    "status": "partial_commit",
                    "message": str(exc),
                    "components": exc.components,
                }
            )
            return 1
        except HostSetupError as exc:
            _print({"status": "invalid_source", "message": str(exc)})
            return 1
        _print(payload)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
