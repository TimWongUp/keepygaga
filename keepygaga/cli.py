from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from keepygaga.config import PROJECT_ROOT, load_config, resolve_config_path
from keepygaga.diagnostics import run_doctor
from keepygaga.memory import initialize_memory_tree

_HOOK_OPTIONS = {"hook_runtime", "hook_python", "hook_config"}


@dataclass(frozen=True)
class HostCliSpec:
    module: str
    function: str
    options: frozenset[str]


_HOST_SPECS = {
    "codex": HostCliSpec(
        "keepygaga.host_setup",
        "setup_codex_host",
        frozenset(_HOOK_OPTIONS | {"codex_home", "codex_binary"}),
    ),
    "claude-code": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_claude_code_host",
        frozenset(_HOOK_OPTIONS | {"host_home"}),
    ),
    "workbuddy": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_workbuddy_host",
        frozenset(_HOOK_OPTIONS | {"host_home"}),
    ),
    "grok": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_grok_host",
        frozenset(_HOOK_OPTIONS | {"host_home", "grok_binary"}),
    ),
    "hermes": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_hermes_host",
        frozenset(_HOOK_OPTIONS | {"host_home"}),
    ),
    "antigravity": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_antigravity_host",
        frozenset(_HOOK_OPTIONS | {"host_home"}),
    ),
}
_HOSTS = tuple(_HOST_SPECS)
_OPTION_FLAGS = {
    "codex_home": "--codex-home",
    "codex_binary": "--codex-binary",
    "host_home": "--host-home",
    "grok_binary": "--grok-binary",
    "hook_runtime": "--hook-runtime",
    "hook_python": "--hook-python",
    "hook_config": "--hook-config",
}


def _validate_host_setup_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    invalid = sorted(
        _OPTION_FLAGS[name]
        for name in _OPTION_FLAGS.keys() - _HOST_SPECS[args.host].options
        if getattr(args, name) is not None
    )
    if invalid:
        parser.error(f"{args.host} does not accept: {', '.join(invalid)}")


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
    setup.add_argument("host", choices=_HOSTS)
    for destination, flag in _OPTION_FLAGS.items():
        setup.add_argument(flag, dest=destination, type=Path)

    return parser


def _print(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "host" and args.host_command == "setup":
        _validate_host_setup_options(args, parser)
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
        from keepygaga.host_common import HostSetupError, HostSetupPartialError

        try:
            spec = _HOST_SPECS[args.host]
            selected_setup = getattr(
                importlib.import_module(spec.module), spec.function
            )
            options = {
                ("hook_config_path" if name == "hook_config" else name): getattr(
                    args, name
                )
                for name in spec.options
            }
            payload = selected_setup(config_path, config, **options)
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
