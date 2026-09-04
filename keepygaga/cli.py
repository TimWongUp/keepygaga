from __future__ import annotations

import argparse
import base64
import binascii
import importlib
import json
import sys
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path

from keepygaga.config import PROJECT_ROOT, load_config, resolve_config_path
from keepygaga.diagnostics import run_doctor
from keepygaga.memory import initialize_memory_tree


@dataclass(frozen=True)
class HostCliSpec:
    module: str
    setup: str
    uninstall: str
    options: frozenset[str]


_HOST_SPECS = {
    "codex": HostCliSpec(
        "keepygaga.host_setup",
        "setup_codex_host",
        "uninstall_codex_host",
        frozenset({"codex_home", "codex_binary"}),
    ),
    "claude-code": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_claude_code_host",
        "uninstall_claude_code_host",
        frozenset({"host_home"}),
    ),
    "workbuddy": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_workbuddy_host",
        "uninstall_workbuddy_host",
        frozenset({"host_home"}),
    ),
    "grok": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_grok_host",
        "uninstall_grok_host",
        frozenset({"host_home", "grok_binary"}),
    ),
    "hermes": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_hermes_host",
        "uninstall_hermes_host",
        frozenset({"host_home"}),
    ),
    "antigravity": HostCliSpec(
        "keepygaga.host_adapters",
        "setup_antigravity_host",
        "uninstall_antigravity_host",
        frozenset({"host_home"}),
    ),
}
_HOSTS = tuple(_HOST_SPECS)
_OPTION_FLAGS = {
    "codex_home": "--codex-home",
    "codex_binary": "--codex-binary",
    "host_home": "--host-home",
    "grok_binary": "--grok-binary",
}


def _decode_config_path(value: str) -> Path:
    try:
        decoded = base64.b64decode(
            value.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (UnicodeError, ValueError, binascii.Error) as exc:
        raise argparse.ArgumentTypeError("invalid encoded configuration path") from exc
    if not decoded or "\x00" in decoded:
        raise argparse.ArgumentTypeError("invalid encoded configuration path")
    path = Path(decoded)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("encoded configuration path must be absolute")
    return path


def _validate_host_options(
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

    install = commands.add_parser("install")
    install.add_argument("--host", action="append", choices=_HOSTS, dest="hosts")
    install.add_argument("--memory-root", type=Path)
    install.add_argument("--yes", action="store_true")

    status = commands.add_parser("status")
    status.add_argument("--latest-version")
    status.add_argument("--host", choices=_HOSTS)

    repair = commands.add_parser("repair")
    repair.add_argument("--yes", action="store_true")

    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("--yes", action="store_true")

    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("--host", action="append", choices=_HOSTS, dest="hosts")
    uninstall.add_argument("--yes", action="store_true")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_commands.add_parser("init")

    hook = commands.add_parser("hook")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    hook_run = hook_commands.add_parser("run")
    hook_run.add_argument("hook", choices=("context", "route", "closeout"))
    hook_run.add_argument("--owner", choices=("keepygaga-hook-v1",))
    hook_run.add_argument(
        "--host",
        required=True,
        choices=("codex", "claude", "workbuddy", "grok", "hermes", "agy_cli"),
    )
    hook_run.add_argument("--event", required=True)
    hook_run.add_argument("--compact", action="store_true")
    hook_run.add_argument(
        "--config-base64",
        type=_decode_config_path,
        dest="hook_config",
        help=argparse.SUPPRESS,
    )

    host = commands.add_parser("host")
    host_commands = host.add_subparsers(dest="host_command", required=True)
    for command_name in ("setup", "uninstall"):
        command = host_commands.add_parser(command_name)
        command.add_argument("host", choices=_HOSTS)
        for destination, flag in _OPTION_FLAGS.items():
            command.add_argument(flag, dest=destination, type=Path)

    return parser


def _print(payload: Mapping[str, object]) -> None:
    with suppress(AttributeError, OSError):
        assert isinstance(sys.stdout, TextIOWrapper)
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _interactive_hosts() -> list[str]:
    detected = [
        host
        for host, path in {
            "codex": Path.home() / ".codex",
            "claude-code": Path.home() / ".claude",
            "workbuddy": Path.home() / ".workbuddy",
            "grok": Path.home() / ".grok",
            "hermes": Path.home() / ".hermes",
            "antigravity": Path.home() / ".gemini",
        }.items()
        if path.exists()
    ]
    suggestions = detected or list(_HOSTS)
    print("Detected or available Agents:")
    for index, host in enumerate(suggestions, start=1):
        print(f"  {index}. {host}")
    raw = input("Select Agents by number, separated with commas: ").strip()
    try:
        selected = [suggestions[int(item.strip()) - 1] for item in raw.split(",")]
    except (ValueError, IndexError) as exc:
        raise ValueError("invalid Agent selection") from exc
    return list(dict.fromkeys(selected))


def _configured_memory_root(config_path: Path) -> Path | None:
    try:
        configured = load_config(config_path)
    except Exception as exc:
        raise ValueError(f"configuration could not be loaded: {exc}") from exc
    if not configured.memory.root.strip():
        return None
    return Path(configured.memory.root).expanduser().resolve()


def _interactive_memory_root(default: Path) -> Path:
    raw = input(f"Memory Root [{default}]: ").strip()
    return Path(raw).expanduser().resolve() if raw else default


def _install_payload(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    config_path: Path,
) -> Mapping[str, object]:
    from keepygaga import installer

    interactive = sys.stdin.isatty()
    if not args.yes and not interactive:
        parser.error("non-interactive install requires --yes and explicit --host")
    configured_root = _configured_memory_root(config_path)
    if args.memory_root:
        memory_root = args.memory_root.expanduser().resolve()
    elif configured_root is not None:
        memory_root = configured_root
        if interactive:
            print(f"Using configured Memory Root: {memory_root}")
    elif interactive:
        memory_root = _interactive_memory_root(installer.default_memory_root().resolve())
    else:
        memory_root = installer.default_memory_root().resolve()
    hosts = args.hosts or (_interactive_hosts() if interactive else [])
    return installer.install(config_path, memory_root, hosts)


def _installer_payload(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    config_path: Path,
) -> Mapping[str, object]:
    from keepygaga import installer

    if args.command == "install":
        return _install_payload(args, parser, config_path)
    if args.command == "status":
        return installer.status(
            config_path,
            latest_version=args.latest_version,
            host=args.host,
        )
    if args.command == "repair":
        if not args.yes:
            parser.error("repair requires --yes")
        return installer.repair(config_path)
    if args.command == "upgrade":
        return installer.upgrade(config_path, apply=args.yes)
    if not args.yes:
        parser.error("uninstall requires --yes")
    return installer.uninstall(config_path, args.hosts or [])


def _run_installer_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    config_path: Path,
) -> int:
    from keepygaga.host_common import HostSetupError, HostSetupPartialError

    try:
        payload = _installer_payload(args, parser, config_path)
    except HostSetupPartialError as exc:
        _print(
            {
                "status": "partial_commit",
                "message": str(exc),
                "components": exc.components,
            }
        )
        return 1
    except (HostSetupError, ValueError) as exc:
        _print({"status": "invalid_source", "message": str(exc)})
        return 1
    _print(payload)
    return 1 if payload.get("status") == "error" else 0


def _run_hook_command(args: argparse.Namespace, config_path: Path) -> int:
    from keepygaga.hooks import closeout as closeout_hook
    from keepygaga.hooks import context as context_hook
    from keepygaga.hooks import route as route_hook

    payload = context_hook.loads_stdin(sys.stdin.read())
    if args.hook == "context":
        result = context_hook.run(config_path, args.host, args.event, payload)
    elif args.hook == "route":
        result = route_hook.run(args.host, args.event, payload, compact=args.compact)
    else:
        result = closeout_hook.run(args.host, args.event, payload)
    _print(result)
    return 0


def _load_command_config(config_path: Path):
    try:
        return load_config(config_path)
    except Exception as exc:
        _print(
            {
                "status": "invalid_source",
                "message": f"configuration could not be loaded: {exc}",
            }
        )
        return None


def _run_memory_command(config_path: Path) -> int:
    config = _load_command_config(config_path)
    if config is None:
        return 1
    if not config.memory.root.strip():
        _print(
            {
                "status": "invalid_source",
                "message": "memory.root is not configured",
            }
        )
        return 1
    payload = initialize_memory_tree(Path(config.memory.root).expanduser(), config.memory)
    _print(payload)
    return 0 if payload["status"] in {"applied", "no_op"} else 1


def _run_host_command(args: argparse.Namespace, config_path: Path) -> int:
    from keepygaga.host_common import HostSetupError, HostSetupPartialError

    config = _load_command_config(config_path)
    if config is None:
        return 1
    try:
        spec = _HOST_SPECS[args.host]
        selected = getattr(
            importlib.import_module(spec.module),
            spec.setup if args.host_command == "setup" else spec.uninstall,
        )
        options = {name: getattr(args, name) for name in spec.options}
        payload = selected(config_path, config, **options)
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "host" and args.host_command in {"setup", "uninstall"}:
        _validate_host_options(args, parser)
    hook_config = getattr(args, "hook_config", None)
    selected_config = hook_config or args.config
    explicit_config = (
        selected_config.expanduser().resolve() if selected_config else None
    )
    config_path = resolve_config_path(explicit_config)

    if args.command in {"install", "status", "repair", "upgrade", "uninstall"}:
        return _run_installer_command(args, parser, config_path)

    if args.command == "doctor":
        payload = run_doctor(config_path, project_root=PROJECT_ROOT)
        _print(payload)
        return 1 if payload["status"] == "error" else 0

    if args.command == "hook" and args.hook_command == "run":
        return _run_hook_command(args, config_path)
    if args.command == "memory" and args.memory_command == "init":
        return _run_memory_command(config_path)

    if args.command == "host" and args.host_command in {"setup", "uninstall"}:
        return _run_host_command(args, config_path)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
