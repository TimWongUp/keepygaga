"""Standalone product installation, observation, repair, upgrade, and removal."""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepygaga import __version__
from keepygaga.config import (
    PROJECT_ROOT,
    KeepygagaConfig,
    MemoryLimitsConfig,
    load_config,
)
from keepygaga.diagnostics import run_doctor
from keepygaga.host_common import (
    HostSetupError,
    HostSetupPartialError,
    atomic_write,
    captured_output,
    load_canonical_contract,
    parse_managed_block,
    run_captured,
)
from keepygaga.launchers import resolve_active_launcher
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

_RELEASE_VERSION_RE = re.compile(
    r"v?(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
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
    limits = MemoryLimitsConfig()
    return (
        f'[memory]\nroot = "{escaped}"\n\n'
        "[memory.limits]\n"
        "# Raise for richer profile/preferences; lower to reduce baseline context.\n"
        f"fixed_page_chars = {limits.fixed_page_chars}\n"
        "# Raise for fewer, larger routed pages; lower to encourage earlier splitting.\n"
        f"dynamic_page_chars = {limits.dynamic_page_chars}\n"
        "# Raise to allow more topic pages; lowering never deletes existing pages.\n"
        f"topics_pages = {limits.topics_pages}\n"
        "# Raise to allow more area pages; lowering never deletes existing pages.\n"
        f"areas_pages = {limits.areas_pages}\n"
        "# Raise to allow more people pages; lowering never deletes existing pages.\n"
        f"people_pages = {limits.people_pages}\n"
    ).encode()


def ensure_config(config_path: Path, memory_root: Path) -> dict[str, object]:
    try:
        existing = config_path.read_bytes() if config_path.exists() else None
    except OSError as exc:
        raise HostSetupError(
            f"Keepygaga config could not be read: {config_path}"
        ) from exc
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
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != INSTALLER_SCHEMA_VERSION
    ):
        raise HostSetupError(
            f"Keepygaga install state has an unsupported schema: {path}"
        )
    return value


def _channel() -> str:
    locations = (
        str(Path(sys.executable)).replace("\\", "/").rstrip("/") + "/",
        str(Path(sys.prefix)).replace("\\", "/").rstrip("/") + "/",
    )
    if any("/uv/tools/keepygaga/" in location for location in locations):
        return "uv-tool"
    if any("/pipx/venvs/keepygaga/" in location for location in locations):
        return "pipx"
    return "python-package"


def _release_version(
    value: str, *, label: str = "latest version"
) -> tuple[str, tuple[int, int, int]]:
    match = _RELEASE_VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise HostSetupError(f"{label} must be a stable release tag such as v0.7.3")
    parts = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    return ".".join(str(part) for part in parts), parts


def _write_state(
    config_path: Path, memory_root: Path, hosts: Mapping[str, object]
) -> None:
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
        raise HostSetupError(
            f"Keepygaga install state could not be written: {path}"
        ) from exc


def _call_host(
    host: str, action: str, config_path: Path, config: KeepygagaConfig
) -> dict[str, object]:
    module_name, setup_name, uninstall_name = _HOST_CALLS[host]
    selected = getattr(
        importlib.import_module(module_name),
        setup_name if action == "setup" else uninstall_name,
    )
    return selected(config_path, config)


def _host_state(host: str) -> dict[str, object]:
    hooks = host != "grok"
    return {
        "reconciled_version": __version__,
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
                        },
                    },
                ) from exc
            raise
        state_hosts[host] = _host_state(host)
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
    changed = (
        config_result.get("status") == "applied"
        or initialized.get("status") == "applied"
        or any(
            isinstance(value, Mapping) and value.get("status") == "applied"
            for value in results.values()
        )
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
        raise HostSetupError(
            "no installed hosts were recorded; select a host explicitly"
        )
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
        codex_home = (
            Path(os.environ.get("CODEX_HOME", "")).expanduser()
            if os.environ.get("CODEX_HOME")
            else home / ".codex"
        )
        resolver = importlib.import_module(
            "keepygaga.host_setup"
        ).resolve_codex_agents_path
        return resolver(codex_home)
    if host == "grok":
        grok_home = home / ".grok"
        if not grok_home.exists():
            return grok_home / "Agents.md"
        resolver = importlib.import_module(
            "keepygaga.host_adapters"
        ).resolve_grok_rules_path
        return resolver(grok_home)
    return {
        "claude-code": home / ".claude" / "CLAUDE.md",
        "workbuddy": home / ".workbuddy" / "CODEBUDDY.md",
        "hermes": home / ".hermes" / "SOUL.md",
        "antigravity": home / ".gemini" / "AGENTS.md",
    }[host]


def _contract_status(host: str) -> str:
    try:
        path = _rules_path(host)
        if not path.exists():
            return "missing"
        text = path.read_text(encoding="utf-8")
        block = parse_managed_block(text, source=str(path))
        canonical = load_canonical_contract()
    except (HostSetupError, OSError, UnicodeError):
        return "conflict"
    if block is None:
        return "missing"
    return "current" if block.text == canonical else "drift"


def _lifecycle_result(
    base: Mapping[str, object], action: str, reason: str
) -> dict[str, object]:
    return {**base, "action": action, "reason": reason}


def _recorded_channel_conflicts(state: Mapping[str, Any], live_channel: str) -> bool:
    recorded = state.get("install_channel")
    return recorded is not None and (
        not isinstance(recorded, str)
        or recorded not in {"uv-tool", "pipx", "python-package"}
        or recorded != live_channel
    )


def _runtime_lifecycle(
    state: Mapping[str, Any], *, latest_version: str, host: str
) -> tuple[dict[str, object], dict[str, object] | None]:
    latest, latest_parts = _release_version(latest_version)
    current, current_parts = _release_version(__version__, label="application version")
    live_channel = _channel()
    base: dict[str, object] = {
        "action": "no_op",
        "current_version": current,
        "latest_version": latest,
        "install_channel": live_channel,
        "host": host,
    }
    if _recorded_channel_conflicts(state, live_channel):
        return base, _lifecycle_result(
            base,
            "manual_review",
            "the live installation owner differs from or is not supported by the recorded owner",
        )
    if current_parts < latest_parts:
        if live_channel not in {"uv-tool", "pipx"}:
            return base, _lifecycle_result(
                base,
                "manual_review",
                f"automatic update is unsupported for {live_channel}",
            )
        return base, _lifecycle_result(
            base, "update", "a newer official release is available"
        )
    if current_parts > latest_parts:
        return base, _lifecycle_result(
            base,
            "manual_review",
            "the running version is newer than the selected official release",
        )
    return base, None


def _memory_source_status(doctor: Mapping[str, object]) -> object:
    checks = doctor.get("checks")
    if not isinstance(checks, list):
        return None
    memory_check = next(
        (
            check
            for check in checks
            if isinstance(check, Mapping) and check.get("id") == "memory_tree"
        ),
        None,
    )
    if not isinstance(memory_check, Mapping):
        return None
    details = memory_check.get("details")
    return details.get("source_status") if isinstance(details, Mapping) else None


def _configured_lifecycle(
    config_path: Path,
    config: KeepygagaConfig,
    state: Mapping[str, Any],
    doctor: Mapping[str, object],
    *,
    host: str,
    base: Mapping[str, object],
) -> dict[str, object]:
    if not config_path.exists() or not config.memory.root.strip():
        return _lifecycle_result(
            base, "initialize", "Keepygaga user data has not been configured"
        )
    raw_hosts = state.get("hosts", {})
    hosts = raw_hosts if isinstance(raw_hosts, Mapping) else {}
    if _memory_source_status(doctor) == "not_initialized":
        action = "repair" if hosts else "initialize"
        return _lifecycle_result(
            base, action, "the configured Memory Root is not initialized"
        )
    if doctor.get("status") == "error":
        return _lifecycle_result(
            base,
            "manual_review",
            "Doctor found an error that must be resolved before changing the installation",
        )
    contract = _contract_status(host)
    if contract == "conflict":
        return _lifecycle_result(
            base,
            "manual_review",
            "the current host Agent Contract has conflicting ownership markers",
        )
    if host not in hosts:
        return _lifecycle_result(
            base, "activate", "the current host is not recorded as active"
        )
    host_state = hosts[host]
    if not isinstance(host_state, Mapping):
        return _lifecycle_result(
            base, "manual_review", "the current host install state is invalid"
        )
    if contract != "current":
        return _lifecycle_result(
            base, "repair", f"the current host Agent Contract is {contract}"
        )
    expected_host_state = _host_state(host)
    if any(host_state.get(key) != value for key, value in expected_host_state.items()):
        return _lifecycle_result(
            base,
            "repair",
            "the current host reconciliation state is stale",
        )
    if state.get("installed_version") != __version__ or state.get(
        "install_channel"
    ) != base.get("install_channel"):
        return _lifecycle_result(
            base,
            "repair",
            "the observational install version or channel is stale",
        )
    return _lifecycle_result(
        base, "no_op", "runtime and current host are already current"
    )


def _lifecycle_plan(
    config_path: Path,
    config: KeepygagaConfig,
    state: Mapping[str, Any],
    doctor: Mapping[str, object],
    *,
    latest_version: str,
    host: str,
) -> dict[str, object]:
    base, runtime_result = _runtime_lifecycle(
        state,
        latest_version=latest_version,
        host=host,
    )
    if runtime_result is not None:
        return runtime_result
    return _configured_lifecycle(
        config_path,
        config,
        state,
        doctor,
        host=host,
        base=base,
    )


def status(
    config_path: Path,
    *,
    latest_version: str | None = None,
    host: str | None = None,
) -> dict[str, object]:
    if (latest_version is None) != (host is None):
        raise HostSetupError(
            "status planning requires --latest-version and --host together"
        )
    state = _load_state(config_path)
    config = load_config(config_path)
    raw_hosts = state.get("hosts", {})
    hosts = list(raw_hosts) if isinstance(raw_hosts, Mapping) else []
    reported_hosts = hosts if host is None else ([host] if host in hosts else [])
    doctor = run_doctor(config_path, project_root=PROJECT_ROOT)
    payload: dict[str, object] = {
        "status": "ok" if doctor.get("status") != "error" else "error",
        "application_version": __version__,
        "install_channel": _channel(),
        "recorded_application_version": state.get("installed_version"),
        "recorded_install_channel": state.get("install_channel"),
        "config_path": str(config_path.resolve()),
        "memory_root": config.memory.root or None,
        "memory_limits": config.memory.limits.as_dict(),
        "limits_source": config.limits_source,
        "doctor": doctor.get("status"),
        "hosts": {
            recorded_host: {
                "recorded": True,
                "contract": _contract_status(recorded_host),
                "live_verified": False,
            }
            for recorded_host in reported_hosts
            if recorded_host in SUPPORTED_HOSTS
        },
        "note": "状态文件仅用于发现；宿主 live 配置与官方诊断仍是最终证据。",
    }
    if latest_version is not None and host is not None:
        payload["lifecycle"] = _lifecycle_plan(
            config_path,
            config,
            state,
            doctor,
            latest_version=latest_version,
            host=host,
        )
    return payload


def _upgrade_command(state: Mapping[str, Any]) -> tuple[str, list[str]]:
    channel = _channel()
    if _recorded_channel_conflicts(state, channel):
        raise HostSetupError(
            "the live installation owner differs from or is not supported by the recorded "
            "owner; resolve it before upgrading"
        )
    if channel == "pipx":
        executable = shutil.which("pipx")
        command = [executable, "upgrade", "keepygaga"] if executable else []
    elif channel == "uv-tool":
        executable = shutil.which("uv")
        command = [executable, "tool", "upgrade", "keepygaga"] if executable else []
    else:
        command = []
    return channel, command


def upgrade(config_path: Path, *, apply: bool) -> dict[str, object]:
    state = _load_state(config_path)
    channel, command = _upgrade_command(state)
    if not command:
        raise HostSetupError(
            f"automatic upgrade for {channel} could not locate its package manager; "
            "reinstall a newer GitHub Release wheel manually"
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
        launcher = resolve_active_launcher("keepygaga")
        repair_command = [
            str(launcher),
            "--config",
            str(config_path.resolve()),
            "repair",
            "--yes",
        ]
        repaired = run_captured(repair_command, timeout=300)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
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
