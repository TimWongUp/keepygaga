"""Standalone product installation, observation, repair, upgrade, and removal."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepygaga import __version__
from keepygaga.config import PROJECT_ROOT, KeepygagaConfig, load_config
from keepygaga.diagnostics import run_doctor
from keepygaga.host_common import (
    HostSetupError,
    HostSetupPartialError,
    atomic_write,
    captured_output,
    parse_managed_block,
    run_captured,
)
from keepygaga.memory import initialize_memory_tree
from keepygaga.version import (
    CONTRACT_VERSION,
    HOOK_PROTOCOL_VERSION,
    INSTALLER_SCHEMA_VERSION,
)

SUPPORTED_HOSTS = (
    "codex",
    "claude-code",
    "workbuddy",
    "grok",
    "hermes",
    "antigravity",
)

_HOST_CALLS = {
    "codex": ("keepygaga.host_setup", "setup_codex_host", "uninstall_codex_host"),
    "claude-code": (
        "keepygaga.host_adapters",
        "setup_claude_code_host",
        "uninstall_claude_code_host",
    ),
    "workbuddy": (
        "keepygaga.host_adapters",
        "setup_workbuddy_host",
        "uninstall_workbuddy_host",
    ),
    "grok": ("keepygaga.host_adapters", "setup_grok_host", "uninstall_grok_host"),
    "hermes": (
        "keepygaga.host_adapters",
        "setup_hermes_host",
        "uninstall_hermes_host",
    ),
    "antigravity": (
        "keepygaga.host_adapters",
        "setup_antigravity_host",
        "uninstall_antigravity_host",
    ),
}


def config_directory() -> Path:
    if os.name == "nt":
        raw = os.environ.get("APPDATA", "").strip()
        if not raw:
            raise HostSetupError("APPDATA is required to locate Keepygaga config")
        return Path(raw).expanduser().resolve() / "Keepygaga"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Keepygaga"
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (
        Path(raw).expanduser().resolve() / "keepygaga"
        if raw
        else Path.home() / ".config" / "keepygaga"
    )


def default_config_path() -> Path:
    return config_directory() / "config.toml"


def default_memory_root() -> Path:
    if os.name == "nt" or sys.platform == "darwin":
        return config_directory() / "agents-memory"
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(raw).expanduser().resolve() if raw else Path.home() / ".local" / "share"
    return base / "keepygaga" / "agents-memory"


def state_path(config_path: Path | None = None) -> Path:
    return (
        config_path.expanduser().resolve().parent
        if config_path is not None
        else config_directory()
    ) / "install-state.json"


def _config_bytes(memory_root: Path) -> bytes:
    escaped = str(memory_root.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'[memory]\nroot = "{escaped}"\n'.encode()


def ensure_config(config_path: Path, memory_root: Path) -> dict[str, object]:
    try:
        existing = config_path.read_bytes() if config_path.exists() else None
    except OSError as exc:
        raise HostSetupError(f"Keepygaga config could not be read: {config_path}") from exc
    if existing is not None:
        configured = load_config(config_path)
        if configured.memory.root.strip():
            live_root = Path(configured.memory.root).expanduser().resolve()
            if live_root != memory_root.resolve():
                raise HostSetupError(
                    f"configured memory root {live_root} differs from requested {memory_root.resolve()}"
                )
            return {"status": "no_op", "path": str(config_path)}
        if existing.strip():
            raise HostSetupError(
                "existing config does not define memory.root; update it explicitly "
                f"instead of allowing install to overwrite {config_path}"
            )
    try:
        status, backup = atomic_write(
            config_path,
            _config_bytes(memory_root),
            expected_original=existing,
        )
    except HostSetupError:
        raise
    except OSError as exc:
        raise HostSetupError(
            f"Keepygaga config could not be written: {config_path}"
        ) from exc
    return {"status": status, "path": str(config_path), "backup": backup}


def _load_state(config_path: Path) -> dict[str, Any]:
    path = state_path(config_path)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(f"Keepygaga install state is invalid: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != INSTALLER_SCHEMA_VERSION:
        raise HostSetupError(f"Keepygaga install state has an unsupported schema: {path}")
    return value


def _channel() -> str:
    executable = str(Path(sys.executable).resolve()).replace("\\", "/")
    if "/uv/tools/keepygaga/" in executable:
        return "uv-tool"
    if "/pipx/venvs/keepygaga/" in executable:
        return "pipx"
    return "python-package"


def _write_state(config_path: Path, memory_root: Path, hosts: Mapping[str, object]) -> None:
    payload = {
        "schema_version": INSTALLER_SCHEMA_VERSION,
        "installed_version": __version__,
        "install_channel": _channel(),
        "config_path": str(config_path.resolve()),
        "memory_root": str(memory_root.resolve()),
        "hosts": dict(hosts),
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    path = state_path(config_path)
    try:
        original = path.read_bytes() if path.exists() else None
        atomic_write(path, encoded, expected_original=original)
    except HostSetupError:
        raise
    except OSError as exc:
        raise HostSetupError(f"Keepygaga install state could not be written: {path}") from exc


def _call_host(host: str, action: str, config_path: Path, config: KeepygagaConfig) -> dict[str, object]:
    module_name, setup_name, uninstall_name = _HOST_CALLS[host]
    selected = getattr(
        importlib.import_module(module_name),
        setup_name if action == "setup" else uninstall_name,
    )
    return selected(config_path, config)


def _host_state(*, hooks: bool) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "hook_protocol_version": HOOK_PROTOCOL_VERSION if hooks else None,
        "hooks_enabled": hooks,
    }


def install(
    config_path: Path,
    memory_root: Path,
    hosts: Sequence[str],
) -> dict[str, object]:
    if not hosts:
        raise HostSetupError("select at least one host")
    unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
    if unknown:
        raise HostSetupError(f"unsupported hosts: {', '.join(unknown)}")
    existing_state = _load_state(config_path)
    config_result = ensure_config(config_path, memory_root)
    config = load_config(config_path)
    initialized = initialize_memory_tree(memory_root, config.memory)
    if initialized.get("status") not in {"applied", "no_op"}:
        if initialized.get("status") == "partial_commit":
            raise HostSetupPartialError(
                "memory initialization partially committed",
                {"config": config_result, "memory": initialized},
            )
        raise HostSetupError(
            f"memory initialization failed: {initialized.get('message', initialized.get('status'))}"
        )
    raw_hosts = existing_state.get("hosts", {})
    state_hosts = dict(raw_hosts) if isinstance(raw_hosts, Mapping) else {}
    results: dict[str, object] = {}
    initialization_applied = (
        config_result.get("status") == "applied"
        or initialized.get("status") == "applied"
    )
    for host in dict.fromkeys(hosts):
        try:
            results[host] = _call_host(host, "setup", config_path, config)
        except HostSetupPartialError as exc:
            raise HostSetupPartialError(
                f"install partially applied before {host} failed: {exc}",
                {
                    "config": config_result,
                    "memory": initialized,
                    "hosts": {**results, host: exc.components},
                },
            ) from exc
        except HostSetupError as exc:
            if results or initialization_applied:
                raise HostSetupPartialError(
                    f"install partially applied before {host} failed: {exc}",
                    {
                        "config": config_result,
                        "memory": initialized,
                        "hosts": {
                            **results,
                            host: {"status": "failed", "message": str(exc)},
                        }
                    },
                ) from exc
            raise
        state_hosts[host] = _host_state(hooks=True)
        try:
            _write_state(config_path, memory_root, state_hosts)
        except HostSetupError as exc:
            raise HostSetupPartialError(
                f"{host} was installed but install state could not be updated: {exc}",
                {
                    "hosts": dict(results),
                    "state": {"status": "failed", "message": str(exc)},
                },
            ) from exc
    changed = config_result.get("status") == "applied" or initialized.get("status") == "applied" or any(
        isinstance(value, Mapping) and value.get("status") == "applied"
        for value in results.values()
    )
    return {
        "status": "applied" if changed else "no_op",
        "version": __version__,
        "config": config_result,
        "memory": initialized,
        "hosts": results,
        "state_path": str(state_path(config_path)),
    }


def uninstall(config_path: Path, hosts: Sequence[str]) -> dict[str, object]:
    state = _load_state(config_path)
    raw_hosts = state.get("hosts", {})
    state_hosts = dict(raw_hosts) if isinstance(raw_hosts, Mapping) else {}
    selected_hosts = list(dict.fromkeys(hosts or tuple(state_hosts)))
    if not selected_hosts:
        raise HostSetupError("no installed hosts were recorded; select a host explicitly")
    unknown = sorted(set(selected_hosts) - set(SUPPORTED_HOSTS))
    if unknown:
        raise HostSetupError(f"unsupported hosts: {', '.join(unknown)}")
    config = load_config(config_path)
    results: dict[str, object] = {}
    for host in selected_hosts:
        try:
            results[host] = _call_host(host, "uninstall", config_path, config)
        except HostSetupPartialError as exc:
            raise HostSetupPartialError(
                f"uninstall partially applied before {host} failed: {exc}",
                {"hosts": {**results, host: exc.components}},
            ) from exc
        except HostSetupError as exc:
            if results:
                raise HostSetupPartialError(
                    f"uninstall partially applied before {host} failed: {exc}",
                    {
                        "hosts": {
                            **results,
                            host: {"status": "failed", "message": str(exc)},
                        }
                    },
                ) from exc
            raise
        state_hosts.pop(host, None)
        memory_root = (
            Path(config.memory.root).expanduser()
            if config.memory.root.strip()
            else default_memory_root()
        )
        try:
            _write_state(config_path, memory_root, state_hosts)
        except HostSetupError as exc:
            raise HostSetupPartialError(
                f"{host} was uninstalled but install state could not be updated: {exc}",
                {
                    "hosts": dict(results),
                    "state": {"status": "failed", "message": str(exc)},
                },
            ) from exc
    memory_root = (
        Path(config.memory.root).expanduser()
        if config.memory.root.strip()
        else default_memory_root()
    )
    return {
        "status": (
            "applied"
            if any(
                isinstance(value, Mapping) and value.get("status") == "applied"
                for value in results.values()
            )
            else "no_op"
        ),
        "hosts": results,
        "memory_preserved": str(memory_root.resolve()),
        "config_preserved": str(config_path.resolve()),
    }


def repair(config_path: Path) -> dict[str, object]:
    state = _load_state(config_path)
    raw_hosts = state.get("hosts", {})
    hosts = list(raw_hosts) if isinstance(raw_hosts, Mapping) else []
    if not hosts:
        raise HostSetupError("no installed hosts were recorded; run install first")
    config = load_config(config_path)
    if not config.memory.root.strip():
        raise HostSetupError("memory.root is not configured")
    return install(
        config_path,
        Path(config.memory.root).expanduser().resolve(),
        hosts,
    )


def _rules_path(host: str) -> Path:
    home = Path.home()
    if host == "codex":
        codex_home = Path(os.environ.get("CODEX_HOME", "")).expanduser() if os.environ.get("CODEX_HOME") else home / ".codex"
        override = codex_home / "AGENTS.override.md"
        return override if override.exists() and override.stat().st_size else codex_home / "AGENTS.md"
    if host == "grok":
        upper = home / ".grok" / "AGENTS.md"
        title = home / ".grok" / "Agents.md"
        if upper.exists() and title.exists():
            return upper if upper.samefile(title) else upper
        return upper if upper.exists() else title
    return {
        "claude-code": home / ".claude" / "CLAUDE.md",
        "workbuddy": home / ".workbuddy" / "CODEBUDDY.md",
        "hermes": home / ".hermes" / "SOUL.md",
        "antigravity": home / ".gemini" / "AGENTS.md",
    }[host]


def _contract_status(host: str) -> str:
    path = _rules_path(host)
    if not path.exists():
        return "missing"
    try:
        text = path.read_text(encoding="utf-8")
        block = parse_managed_block(text, source=str(path))
    except Exception:
        return "conflict"
    if block is None:
        return "missing"
    return "current" if f"KEEPYGAGA:CONTRACT:{CONTRACT_VERSION}" in block.text else "drift"


def status(config_path: Path) -> dict[str, object]:
    state = _load_state(config_path)
    config = load_config(config_path)
    raw_hosts = state.get("hosts", {})
    hosts = list(raw_hosts) if isinstance(raw_hosts, Mapping) else []
    doctor = run_doctor(config_path, project_root=PROJECT_ROOT)
    return {
        "status": "ok" if doctor.get("status") != "error" else "error",
        "application_version": __version__,
        "install_channel": state.get("install_channel", "unknown"),
        "config_path": str(config_path.resolve()),
        "memory_root": config.memory.root or None,
        "doctor": doctor.get("status"),
        "hosts": {
            host: {
                "recorded": True,
                "contract": _contract_status(host),
                "live_verified": False,
            }
            for host in hosts
            if host in SUPPORTED_HOSTS
        },
        "note": "状态文件仅用于发现；宿主 live 配置与官方诊断仍是最终证据。",
    }


def upgrade(config_path: Path, *, apply: bool) -> dict[str, object]:
    state = _load_state(config_path)
    channel = str(state.get("install_channel") or _channel())
    if channel == "pipx":
        executable = shutil.which("pipx")
        command = [executable, "upgrade", "keepygaga"] if executable else []
    else:
        executable = shutil.which("uv")
        command = [executable, "tool", "upgrade", "keepygaga"] if executable else []
    if not command:
        raise HostSetupError(
            f"automatic upgrade for {channel} could not locate its package manager; "
            "reinstall the latest GitHub/PyPI release manually"
        )
    if not apply:
        return {
            "status": "approval_required",
            "command": command,
            "message": "rerun with --yes to upgrade the installed release and repair recorded hosts",
        }
    try:
        completed = run_captured(command, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"Keepygaga upgrade could not be started: {exc}") from exc
    if completed.returncode != 0:
        detail = captured_output(completed) or "unknown uv error"
        raise HostSetupError(f"Keepygaga upgrade failed: {detail}")
    raw_hosts = state.get("hosts", {})
    if not isinstance(raw_hosts, Mapping) or not raw_hosts:
        return {
            "status": "applied",
            "command": command,
            "repair": "skipped",
            "message": "runtime upgraded; no recorded hosts required repair",
        }
    upgrade_component = {"status": "applied", "command": command}
    try:
        launcher = shutil.which("keepygaga")
        if launcher is None:
            raise OSError("Keepygaga launcher could not be located after upgrade")
        repair_command = [
            launcher,
            "--config",
            str(config_path.resolve()),
            "repair",
            "--yes",
        ]
        repaired = run_captured(repair_command, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupPartialError(
            f"Keepygaga upgraded but repair could not be started: {exc}",
            {
                "upgrade": upgrade_component,
                "repair": {"status": "failed", "message": str(exc)},
            },
        ) from exc
    if repaired.returncode != 0:
        detail = captured_output(repaired) or "unknown repair error"
        raise HostSetupPartialError(
            f"Keepygaga upgraded but host repair failed: {detail}",
            {
                "upgrade": upgrade_component,
                "repair": {
                    "status": "failed",
                    "command": repair_command,
                    "message": detail,
                },
            },
        )
    return {
        "status": "applied",
        "command": command,
        "repair_command": repair_command,
        "message": "runtime upgraded and recorded hosts reconciled",
    }
