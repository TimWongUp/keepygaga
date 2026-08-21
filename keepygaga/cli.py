from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from keepygaga.config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, load_config
from keepygaga.diagnostics import run_doctor
from keepygaga.memory import initialize_memory_tree


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keepygaga",
        description="Run a Keepygaga core-memory maintenance command.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    commands = parser.add_subparsers(dest="command")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_commands.add_parser("init")

    return parser


def _print(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    config_path = args.config.expanduser().resolve()
    if args.command == "doctor":
        payload = run_doctor(config_path, project_root=PROJECT_ROOT)
        _print(payload)
        return 1 if payload["status"] == "error" else 0

    config = load_config(config_path)
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
        return 0 if payload["status"] == "applied" else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
