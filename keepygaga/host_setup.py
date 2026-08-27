from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from keepygaga import __version__
from keepygaga import host_common as _host_common
from keepygaga.config import KeepygagaConfig
from keepygaga.hooks import build_fragment, merge_hook_fragment
from keepygaga.host_common import (
    END_MARKER,
    EXPECTED_ANY,
    HOOK_ENTRYPOINTS,
    START_MARKER,
    HostSetupError,
    HostSetupPartialError,
    atomic_write,
    default_hook_config_path,
    ensure_regular_target,
    exclusive_backup,
    json_result,
    load_canonical_contract,
    load_hook_merger,
    load_legacy_contract,
    merge_managed_contract,
    parse_managed_block,
    prepare_hook_runtime_config,
    probe_hook_python,
    probe_keepygaga_python,
    read_utf8,
    remove_managed_contract,
    render_fragment,
    validate_hook_command_path,
    validate_host_source,
)
from keepygaga.launchers import resolve_launcher

HOOK_FRAGMENT_RELATIVE_PATH = Path("config/hooks/codex.json")

# Compatibility re-exports for callers that imported the former monolithic module.
CONTRACT_RELATIVE_PATH = _host_common.CONTRACT_RELATIVE_PATH
HOOK_MERGER_RELATIVE_PATH = _host_common.HOOK_MERGER_RELATIVE_PATH
LEGACY_CONTRACT_RELATIVE_PATH = _host_common.LEGACY_CONTRACT_RELATIVE_PATH
VERSION_PREFIX = _host_common.VERSION_PREFIX
ManagedBlock = _host_common.ManagedBlock

_EXPECTED_ANY = EXPECTED_ANY
_atomic_write = atomic_write
_default_hook_config_path = default_hook_config_path
_ensure_regular_target = ensure_regular_target
_exclusive_backup = exclusive_backup
_json_result = json_result
_load_hook_merger = load_hook_merger
_probe_hook_python = probe_hook_python
_probe_keepygaga_python = probe_keepygaga_python
_read_utf8 = read_utf8
_render_fragment = render_fragment
_validate_hook_command_path = validate_hook_command_path


@dataclass(frozen=True)
class CodexHookPlan:
    hooks_path: Path
    hooks_original: bytes | None
    hook_config_path: Path
    hook_config_original: bytes | None
    hook_config_content: bytes
    memory_root: Path
    selected_python: Path
    selected_runtime: Path
    merged: dict[str, Any]
    builtin: bool = False
    config_path: Path | None = None


@dataclass(frozen=True)
class CodexMcpPlan:
    codex_home: Path
    codex_config: Path
    config_original: bytes | None
    selected_python: Path
    selected_args: tuple[str, ...]
    selected_codex: Path
    desired_env: dict[str, str]
    current_payload: Mapping[str, Any] | None
    needs_update: bool


def _read_codex_rules_candidate(path: Path) -> tuple[bytes | None, str]:
    """Read a Codex rules candidate without changing its original bytes."""
    if path.is_symlink() or path.exists():
        _ensure_regular_target(path)
    if not path.exists():
        return None, ""
    try:
        original = path.read_bytes()
        return original, original.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(f"could not read UTF-8 file: {path}") from exc


def _select_codex_rules_candidate(
    codex_home: Path,
) -> tuple[Path, bytes | None, str]:
    override = codex_home / "AGENTS.override.md"
    agents = codex_home / "AGENTS.md"
    override_original, override_text = _read_codex_rules_candidate(override)
    agents_original, agents_text = _read_codex_rules_candidate(agents)
    if override_original is not None and override_text.strip():
        if START_MARKER in agents_text or END_MARKER in agents_text:
            parse_managed_block(agents_text, source=str(agents))
            raise HostSetupError(
                f"non-effective Codex rules candidate contains a stale Keepygaga "
                f"managed block: {agents}"
            )
        return override, override_original, override_text
    return agents, agents_original, agents_text


def resolve_codex_agents_path(codex_home: Path) -> Path:
    target, _original, _text = _select_codex_rules_candidate(codex_home)
    return target


def reconcile_codex_rules(
    codex_home: Path,
    *,
    contract_path: Path | None = None,
    legacy_contract_path: Path | None = None,
) -> dict[str, object]:
    canonical = load_canonical_contract(contract_path)
    legacy = load_legacy_contract(legacy_contract_path)
    target, original, existing = _select_codex_rules_candidate(codex_home)
    merged = merge_managed_contract(
        existing, canonical, source=str(target), legacy=legacy
    )
    verified_target, verified_original, verified_existing = (
        _select_codex_rules_candidate(codex_home)
    )
    if (
        verified_target != target
        or verified_original != original
        or verified_existing != existing
    ):
        raise HostSetupError("Codex rules candidates changed during reconciliation")
    status, backup = _atomic_write(
        target, merged.encode("utf-8"), expected_original=original
    )
    return _json_result(status, path=str(target), backup=backup)


def _run_codex(
    codex_binary: Path,
    codex_home: Path,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    try:
        return subprocess.run(
            [str(codex_binary), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"Codex CLI could not be executed: {exc}") from exc


def _matching_mcp_registration(
    payload: Mapping[str, Any],
    command: Path,
    args: tuple[str, ...],
    expected_env: Mapping[str, str],
) -> bool:
    transport = payload.get("transport")
    if not isinstance(transport, Mapping):
        return False
    return (
        payload.get("enabled") is True
        and transport.get("type") == "stdio"
        and transport.get("command") == str(command)
        and transport.get("args") == list(args)
        and transport.get("env") == dict(expected_env)
        and transport.get("env_vars") in (None, [])
        and transport.get("cwd") is None
    )


def _mcp_environment(payload: Mapping[str, Any]) -> dict[str, str]:
    transport = payload.get("transport")
    if not isinstance(transport, Mapping):
        raise HostSetupError("existing Keepygaga MCP transport is invalid")
    environment = transport.get("env")
    if environment is None:
        return {}
    if not isinstance(environment, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise HostSetupError("existing Keepygaga MCP environment is invalid")
    supported = {"KEEPYGAGA_CONFIG", "KEEPYGAGA_WRITER"}
    return {key: value for key, value in environment.items() if key in supported}


def _ensure_replaceable_mcp(payload: Mapping[str, Any]) -> None:
    transport = payload.get("transport")
    if not isinstance(transport, Mapping) or transport.get("type") != "stdio":
        raise HostSetupError(
            "existing Keepygaga MCP registration is not stdio; resolve it manually"
        )
    if transport.get("env_vars") not in (None, []):
        raise HostSetupError(
            "existing Keepygaga MCP env_vars cannot be preserved automatically"
        )
    if transport.get("cwd") is not None:
        raise HostSetupError(
            "existing Keepygaga MCP cwd cannot be preserved automatically"
        )
    for field in (
        "enabled_tools",
        "disabled_tools",
        "startup_timeout_sec",
        "tool_timeout_sec",
    ):
        if payload.get(field) is not None:
            raise HostSetupError(
                f"existing Keepygaga MCP {field} cannot be preserved automatically"
            )


def _prepare_codex_mcp(
    codex_home: Path,
    config_path: Path,
    *,
    python: Path | None = None,
    codex_binary: Path | None = None,
) -> CodexMcpPlan:
    if python is not None:
        selected_python = Path(os.path.abspath(python.expanduser()))
        if not selected_python.is_file():
            raise HostSetupError(f"Keepygaga Python does not exist: {selected_python}")
        _probe_keepygaga_python(selected_python)
        selected_args = ("-m", "keepygaga.server")
    else:
        try:
            selected_python = resolve_launcher("keepygaga-mcp")
        except RuntimeError as exc:
            raise HostSetupError(str(exc)) from exc
        selected_args = ()
    selected_codex = codex_binary or (
        Path(found).resolve() if (found := shutil.which("codex")) else None
    )
    if (
        selected_codex is None
        or not selected_codex.is_file()
        or not os.access(selected_codex, os.X_OK)
    ):
        raise HostSetupError("Codex CLI could not be located")

    codex_config = codex_home / "config.toml"
    _ensure_regular_target(codex_config)
    config_original = codex_config.read_bytes() if codex_config.exists() else None

    current = _run_codex(
        selected_codex, codex_home, ["mcp", "get", "keepygaga", "--json"]
    )
    desired_env = {"KEEPYGAGA_CONFIG": str(config_path)}
    current_payload: Mapping[str, Any] | None = None
    if current.returncode == 0:
        try:
            loaded_payload = json.loads(current.stdout)
        except json.JSONDecodeError as exc:
            raise HostSetupError(
                "Codex returned invalid MCP registration JSON"
            ) from exc
        if not isinstance(loaded_payload, Mapping):
            raise HostSetupError("Codex returned an invalid MCP registration object")
        current_payload = loaded_payload
        _ensure_replaceable_mcp(current_payload)
        desired_env = _mcp_environment(current_payload)
        desired_env["KEEPYGAGA_CONFIG"] = str(config_path)
        if _matching_mcp_registration(
            current_payload, selected_python, selected_args, desired_env
        ):
            return CodexMcpPlan(
                codex_home=codex_home,
                codex_config=codex_config,
                config_original=config_original,
                selected_python=selected_python,
                selected_args=selected_args,
                selected_codex=selected_codex,
                desired_env=desired_env,
                current_payload=current_payload,
                needs_update=False,
            )
    elif "No MCP server named" not in f"{current.stderr}\n{current.stdout}":
        detail = (
            current.stderr.strip() or current.stdout.strip() or "unknown Codex error"
        )
        raise HostSetupError(f"Codex MCP registration could not be read: {detail}")

    return CodexMcpPlan(
        codex_home=codex_home,
        codex_config=codex_config,
        config_original=config_original,
        selected_python=selected_python,
        selected_args=selected_args,
        selected_codex=selected_codex,
        desired_env=desired_env,
        current_payload=current_payload,
        needs_update=True,
    )


def _apply_codex_mcp_plan(plan: CodexMcpPlan) -> dict[str, object]:
    if not plan.needs_update:
        current = _run_codex(
            plan.selected_codex,
            plan.codex_home,
            ["mcp", "get", "keepygaga", "--json"],
        )
        try:
            current_payload = json.loads(current.stdout)
        except json.JSONDecodeError as exc:
            raise HostSetupError(
                "Keepygaga MCP registration changed after preflight"
            ) from exc
        if (
            current.returncode != 0
            or not isinstance(current_payload, Mapping)
            or not _matching_mcp_registration(
                current_payload,
                plan.selected_python,
                plan.selected_args,
                plan.desired_env,
            )
        ):
            raise HostSetupError("Keepygaga MCP registration changed after preflight")
        return _json_result("no_op", key="keepygaga")
    live_config = plan.codex_config.read_bytes() if plan.codex_config.exists() else None
    if live_config != plan.config_original:
        raise HostSetupError(f"write conflict while updating {plan.codex_config}")

    environment_arguments = [
        value
        for key in sorted(plan.desired_env)
        for value in ("--env", f"{key}={plan.desired_env[key]}")
    ]
    config_backup = (
        _exclusive_backup(plan.codex_config, plan.config_original)
        if plan.config_original is not None
        else None
    )
    added = _run_codex(
        plan.selected_codex,
        plan.codex_home,
        [
            "mcp",
            "add",
            "keepygaga",
            *environment_arguments,
            "--",
            str(plan.selected_python),
            *plan.selected_args,
        ],
    )
    if added.returncode != 0:
        detail = added.stderr.strip() or added.stdout.strip() or "unknown Codex error"
        raise HostSetupError(f"Codex MCP registration failed: {detail}")
    try:
        verified = _run_codex(
            plan.selected_codex,
            plan.codex_home,
            ["mcp", "get", "keepygaga", "--json"],
        )
        verified_payload = json.loads(verified.stdout)
        if verified.returncode != 0 or not isinstance(verified_payload, Mapping):
            raise HostSetupError("Codex MCP registration could not be verified")
        if not _matching_mcp_registration(
            verified_payload,
            plan.selected_python,
            plan.selected_args,
            plan.desired_env,
        ):
            raise HostSetupError(
                "Codex MCP registration does not match the requested transport"
            )
    except (HostSetupError, json.JSONDecodeError) as exc:
        recovery: dict[str, object]
        if config_backup is not None:
            recovery = {
                "action": "restore_file",
                "source": str(config_backup),
                "destination": str(plan.codex_config),
            }
        elif plan.current_payload is None:
            removed = _run_codex(
                plan.selected_codex,
                plan.codex_home,
                ["mcp", "remove", "keepygaga"],
            )
            recovery = {
                "action": "remove_new_registration",
                "status": "applied" if removed.returncode == 0 else "failed",
            }
        else:
            recovery = {
                "action": "manual_restore_required",
                "reason": "the previous registration came from outside config.toml",
            }
        raise HostSetupPartialError(
            f"Codex accepted the MCP update but verification failed: {exc}",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    verified=False,
                    backup=str(config_backup) if config_backup else None,
                    recovery=recovery,
                )
            },
        ) from exc
    return _json_result(
        "applied",
        key="keepygaga",
        backup=str(config_backup) if config_backup else None,
    )


def reconcile_codex_mcp(
    codex_home: Path,
    config_path: Path,
    *,
    python: Path | None = None,
    codex_binary: Path | None = None,
) -> dict[str, object]:
    plan = _prepare_codex_mcp(
        codex_home,
        config_path,
        python=python,
        codex_binary=codex_binary,
    )
    return _apply_codex_mcp_plan(plan)


def _reconcile_hook_runtime_config(path: Path, memory_root: Path) -> dict[str, object]:
    original, content = prepare_hook_runtime_config(path, memory_root)
    status, backup = _atomic_write(path, content, expected_original=original)
    return _json_result(status, path=str(path), backup=backup)


def _prepare_codex_hooks(
    codex_home: Path,
    memory_root: Path,
    runtime_root: Path | None,
    hook_python: Path | None,
    *,
    config_path: Path | None = None,
    hook_config_path: Path | None = None,
) -> CodexHookPlan:
    if runtime_root is None and hook_python is None:
        if config_path is None:
            raise HostSetupError("config path is required for built-in Keepygaga Hooks")
        try:
            launcher = resolve_launcher("keepygaga")
        except RuntimeError as exc:
            raise HostSetupError(str(exc)) from exc
        rendered = build_fragment(
            "codex",
            launcher=launcher,
            config_path=config_path.resolve(),
        )
        hooks_path = codex_home / "hooks.json"
        _ensure_regular_target(hooks_path)
        hooks_original = hooks_path.read_bytes() if hooks_path.exists() else None
        existing: dict[str, Any] = {}
        if hooks_original is not None:
            try:
                loaded = json.loads(hooks_original.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise HostSetupError(
                    f"Codex hooks file is invalid JSON: {hooks_path}"
                ) from exc
            if not isinstance(loaded, dict):
                raise HostSetupError(
                    f"Codex hooks file must be an object: {hooks_path}"
                )
            existing = loaded
        try:
            merged = merge_hook_fragment(existing, rendered)
        except Exception as exc:
            raise HostSetupError(f"Keepygaga rejected Codex hooks: {exc}") from exc
        return CodexHookPlan(
            hooks_path=hooks_path,
            hooks_original=hooks_original,
            hook_config_path=Path("."),
            hook_config_original=None,
            hook_config_content=b"",
            memory_root=memory_root,
            selected_python=Path(os.path.abspath(sys.executable)),
            selected_runtime=launcher,
            merged=merged,
            builtin=True,
            config_path=config_path.resolve(),
        )
    if runtime_root is None or hook_python is None:
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    raw_runtime = runtime_root.expanduser()
    if raw_runtime.is_symlink():
        raise HostSetupError(
            f"Agent Hook Runtime root must not be a symlink: {raw_runtime}"
        )
    selected_runtime = raw_runtime.resolve()
    selected_python = Path(os.path.abspath(hook_python.expanduser()))
    if not selected_runtime.is_dir():
        raise HostSetupError(f"Agent Hook Runtime root is invalid: {selected_runtime}")
    if not selected_python.is_file():
        raise HostSetupError(f"Hook Python is invalid: {selected_python}")
    _probe_hook_python(selected_python)
    _validate_hook_command_path(selected_runtime, label="Agent Hook Runtime root")
    _validate_hook_command_path(selected_python, label="Hook Python")
    for relative in HOOK_ENTRYPOINTS:
        entrypoint = selected_runtime / relative
        if not entrypoint.is_file() or entrypoint.is_symlink():
            raise HostSetupError(
                f"Agent Hook Runtime entrypoint is missing: {entrypoint}"
            )

    fragment_path = selected_runtime / HOOK_FRAGMENT_RELATIVE_PATH
    if fragment_path.is_symlink() or not fragment_path.is_file():
        raise HostSetupError(
            f"Codex Hook fragment must be a regular file: {fragment_path}"
        )
    try:
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(
            f"Codex Hook fragment could not be loaded: {fragment_path}"
        ) from exc
    if not isinstance(fragment, dict) or fragment.get("host") != "codex":
        raise HostSetupError("Agent Hook Runtime Codex fragment is invalid")
    rendered = _render_fragment(
        fragment,
        {"{{PYTHON}}": str(selected_python), "{{RUNTIME_ROOT}}": str(selected_runtime)},
    )
    if not isinstance(rendered, dict):
        raise HostSetupError("rendered Codex Hook fragment is invalid")
    markers = rendered.get("owned_command_markers")
    if not isinstance(markers, list):
        raise HostSetupError("rendered Codex Hook ownership markers are invalid")
    markers.extend(str(selected_runtime / relative) for relative in HOOK_ENTRYPOINTS)

    default_hook_config = _default_hook_config_path()
    selected_hook_config = (
        Path(os.path.abspath(hook_config_path.expanduser()))
        if hook_config_path is not None
        else default_hook_config
    )
    if selected_hook_config != default_hook_config:
        raise HostSetupError(
            "selected Hook config is not the path Agent Hook Runtime will load; "
            "set AGENT_HOOK_RUNTIME_CONFIG to the same absolute path"
        )
    hook_config_original, hook_config_content = prepare_hook_runtime_config(
        selected_hook_config, memory_root
    )
    environment_root = os.environ.get("AGENT_HOOK_RUNTIME_MEMORY_ROOT", "").strip()
    if environment_root:
        environment_path = Path(environment_root).expanduser()
        if not environment_path.is_absolute():
            raise HostSetupError("AGENT_HOOK_RUNTIME_MEMORY_ROOT must be absolute")
        if environment_path.resolve() != memory_root:
            raise HostSetupError(
                "AGENT_HOOK_RUNTIME_MEMORY_ROOT conflicts with configured memory.root"
            )

    hooks_path = codex_home / "hooks.json"
    _ensure_regular_target(hooks_path)
    hooks_original = hooks_path.read_bytes() if hooks_path.exists() else None
    existing: dict[str, Any] = {}
    if hooks_path.exists():
        try:
            loaded = json.loads(_read_utf8(hooks_path))
        except json.JSONDecodeError as exc:
            raise HostSetupError(
                f"Codex hooks file is invalid JSON: {hooks_path}"
            ) from exc
        if not isinstance(loaded, dict):
            raise HostSetupError(f"Codex hooks file must be an object: {hooks_path}")
        existing = loaded
    merger = _load_hook_merger(selected_runtime)
    try:
        merged = merger(existing, rendered)
    except Exception as exc:
        raise HostSetupError(f"Agent Hook Runtime rejected Codex hooks: {exc}") from exc
    if not isinstance(merged, dict):
        raise HostSetupError("Agent Hook Runtime merger must return a JSON object")
    merged_hooks = merged.get("hooks")
    if not isinstance(merged_hooks, dict) or not all(
        isinstance(event, str) and isinstance(entries, list)
        for event, entries in merged_hooks.items()
    ):
        raise HostSetupError("Agent Hook Runtime merger returned invalid Codex hooks")
    try:
        json.dumps(merged, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HostSetupError(
            "Agent Hook Runtime merger returned non-JSON data"
        ) from exc

    return CodexHookPlan(
        hooks_path=hooks_path,
        hooks_original=hooks_original,
        hook_config_path=selected_hook_config,
        hook_config_original=hook_config_original,
        hook_config_content=hook_config_content,
        memory_root=memory_root,
        selected_python=selected_python,
        selected_runtime=selected_runtime,
        merged=merged,
    )


def _run_hook_smoke(plan: CodexHookPlan) -> None:
    smoke_environment = {
        key: value
        for key in (
            "APPDATA",
            "HOME",
            "LOCALAPPDATA",
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "USERPROFILE",
            "WINDIR",
            "XDG_CONFIG_HOME",
        )
        if (value := os.environ.get(key)) is not None
    }
    if not plan.builtin:
        smoke_environment["AGENT_HOOK_RUNTIME_CONFIG"] = str(plan.hook_config_path)
    command = (
        [
            str(plan.selected_python),
            "-m",
            "keepygaga.cli",
            "--config",
            str(plan.config_path),
            "hook",
            "run",
            "context",
            "--host",
            "codex",
            "--event",
            "SessionStart",
        ]
        if plan.builtin
        else [
            str(plan.selected_python),
            str(plan.selected_runtime / "hooks/context_hook.py"),
            "codex",
        ]
    )
    try:
        smoke = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input="{}",
            text=True,
            env=smoke_environment,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"Codex context Hook smoke could not run: {exc}") from exc
    if smoke.returncode != 0:
        detail = smoke.stderr.strip()[:500]
        suffix = f": {detail}" if detail else ""
        raise HostSetupError(f"Codex context Hook smoke failed{suffix}")
    try:
        smoke_payload = json.loads(smoke.stdout)
    except json.JSONDecodeError as exc:
        detail = smoke.stderr.strip()[:500]
        suffix = f": {detail}" if detail else ""
        raise HostSetupError(
            f"Codex context Hook smoke returned invalid JSON{suffix}"
        ) from exc
    if not isinstance(smoke_payload, dict):
        raise HostSetupError("Codex context Hook smoke returned a non-object")


def _apply_codex_hooks_plan(plan: CodexHookPlan) -> dict[str, object]:
    live_hooks = plan.hooks_path.read_bytes() if plan.hooks_path.exists() else None
    if live_hooks != plan.hooks_original:
        raise HostSetupError(f"write conflict while updating {plan.hooks_path}")
    if plan.builtin:
        hook_config = _json_result(
            "no_op", reason="built-in Keepygaga Hooks use the main config"
        )
    else:
        hook_config_status, hook_config_backup = _atomic_write(
            plan.hook_config_path,
            plan.hook_config_content,
            expected_original=plan.hook_config_original,
        )
        hook_config = _json_result(
            hook_config_status,
            path=str(plan.hook_config_path),
            backup=hook_config_backup,
        )
    try:
        _run_hook_smoke(plan)
    except Exception as exc:
        if hook_config["status"] == "applied":
            raise HostSetupPartialError(
                f"Agent Hook Runtime config was updated but Hook smoke failed: {exc}",
                {
                    "hooks": _json_result(
                        "partial", runtime_config=hook_config, smoke="failed"
                    )
                },
            ) from exc
        raise
    encoded = (json.dumps(plan.merged, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    try:
        status, backup = _atomic_write(
            plan.hooks_path,
            encoded,
            expected_original=plan.hooks_original,
        )
    except Exception as exc:
        if hook_config["status"] == "applied":
            raise HostSetupPartialError(
                f"Agent Hook Runtime config was updated but Codex hooks failed: {exc}",
                {
                    "hooks": _json_result(
                        "partial", runtime_config=hook_config, smoke="ok"
                    )
                },
            ) from exc
        raise
    return _json_result(
        "applied" if "applied" in {status, hook_config["status"]} else "no_op",
        path=str(plan.hooks_path),
        backup=backup,
        runtime_config=hook_config,
        smoke="ok",
    )


def reconcile_codex_hooks(
    codex_home: Path,
    memory_root: Path,
    runtime_root: Path,
    hook_python: Path,
    *,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    plan = _prepare_codex_hooks(
        codex_home,
        memory_root,
        runtime_root,
        hook_python,
        hook_config_path=hook_config_path,
    )
    return _apply_codex_hooks_plan(plan)


def _resolve_codex_home(codex_home: Path | None, *, create: bool) -> Path:
    if codex_home is not None:
        raw_home = codex_home.expanduser()
    else:
        configured_home = os.environ.get("CODEX_HOME", "").strip()
        raw_home = (
            Path(configured_home).expanduser()
            if configured_home
            else Path.home() / ".codex"
        )
    if not raw_home.is_absolute():
        raise HostSetupError(f"Codex home must be an absolute path: {raw_home}")
    if raw_home.is_symlink():
        raise HostSetupError(f"Codex home must not be a symlink: {raw_home}")
    selected_home = raw_home.resolve()
    if selected_home.exists() and not selected_home.is_dir():
        raise HostSetupError(f"Codex home is not a directory: {selected_home}")
    if create:
        try:
            selected_home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HostSetupError(f"Codex home could not be created: {exc}") from exc
    return selected_home


def setup_codex_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    codex_home: Path | None = None,
    codex_binary: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    if (hook_runtime is None) != (hook_python is None):
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    memory_root, doctor = validate_host_source(config_path, config)
    selected_home = _resolve_codex_home(codex_home, create=True)

    lock = FileLock(str(selected_home / ".keepygaga-host-setup.lock"), timeout=30)
    components: dict[str, object] = {}
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"Codex setup lock could not be acquired: {exc}") from exc
    try:
        try:
            hook_plan = _prepare_codex_hooks(
                selected_home,
                memory_root,
                hook_runtime,
                hook_python,
                config_path=config_path,
                hook_config_path=hook_config_path,
            )
            mcp_plan = _prepare_codex_mcp(
                selected_home,
                config_path.resolve(),
                codex_binary=codex_binary,
            )
            mcp = _apply_codex_mcp_plan(mcp_plan)
            components["mcp"] = mcp
            rules = reconcile_codex_rules(selected_home)
            components["rules"] = rules
            hooks = _apply_codex_hooks_plan(hook_plan)
            components["hooks"] = hooks
        except HostSetupPartialError as exc:
            components.update(exc.components)
            raise HostSetupPartialError(str(exc), components) from exc
        except Exception as exc:
            if any(
                isinstance(value, Mapping) and value.get("status") == "applied"
                for value in components.values()
            ):
                raise HostSetupPartialError(str(exc), components) from exc
            if isinstance(exc, HostSetupError):
                raise
            raise HostSetupError(str(exc)) from exc
    finally:
        lock.release()

    component_statuses = {rules["status"], mcp["status"], hooks["status"]}
    overall = "applied" if "applied" in component_statuses else "no_op"
    return _json_result(
        overall,
        host="codex",
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        rules=rules,
        mcp=mcp,
        hooks=hooks,
        restart_required=True,
    )


def _load_codex_hook_fragment(
    runtime_root: Path,
    hook_python: Path,
) -> tuple[Path, Path, dict[str, Any], Any]:
    raw_runtime = runtime_root.expanduser()
    if raw_runtime.is_symlink():
        raise HostSetupError(
            f"Agent Hook Runtime root must not be a symlink: {raw_runtime}"
        )
    selected_runtime = raw_runtime.resolve()
    selected_python = Path(os.path.abspath(hook_python.expanduser()))
    if not selected_runtime.is_dir():
        raise HostSetupError(f"Agent Hook Runtime root is invalid: {selected_runtime}")
    if not selected_python.is_file():
        raise HostSetupError(f"Hook Python is invalid: {selected_python}")
    _probe_hook_python(selected_python)
    _validate_hook_command_path(selected_runtime, label="Agent Hook Runtime root")
    _validate_hook_command_path(selected_python, label="Hook Python")
    for relative in HOOK_ENTRYPOINTS:
        entrypoint = selected_runtime / relative
        if not entrypoint.is_file() or entrypoint.is_symlink():
            raise HostSetupError(
                f"Agent Hook Runtime entrypoint is missing: {entrypoint}"
            )
    fragment_path = selected_runtime / HOOK_FRAGMENT_RELATIVE_PATH
    if fragment_path.is_symlink() or not fragment_path.is_file():
        raise HostSetupError(
            f"Codex Hook fragment must be a regular file: {fragment_path}"
        )
    try:
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(
            f"Codex Hook fragment could not be loaded: {fragment_path}"
        ) from exc
    if not isinstance(fragment, dict) or fragment.get("host") != "codex":
        raise HostSetupError("Agent Hook Runtime Codex fragment is invalid")
    rendered = _render_fragment(
        fragment,
        {"{{PYTHON}}": str(selected_python), "{{RUNTIME_ROOT}}": str(selected_runtime)},
    )
    if not isinstance(rendered, dict):
        raise HostSetupError("rendered Codex Hook fragment is invalid")
    markers = rendered.get("owned_command_markers")
    if not isinstance(markers, list):
        raise HostSetupError("rendered Codex Hook ownership markers are invalid")
    markers.extend(str(selected_runtime / relative) for relative in HOOK_ENTRYPOINTS)
    merger = _load_hook_merger(selected_runtime)
    return selected_runtime, selected_python, rendered, merger


def _prepare_codex_hook_strip(
    codex_home: Path,
    runtime_root: Path | None,
    hook_python: Path | None,
    *,
    config_path: Path,
    hook_config_path: Path | None = None,
) -> CodexHookPlan:
    del hook_config_path
    builtin = runtime_root is None and hook_python is None
    if builtin:
        try:
            selected_runtime = resolve_launcher("keepygaga")
        except RuntimeError as exc:
            raise HostSetupError(str(exc)) from exc
        selected_python = Path(sys.executable).resolve()
        rendered = build_fragment(
            "codex",
            launcher=selected_runtime,
            config_path=config_path.resolve(),
            enabled=False,
        )
        merger = merge_hook_fragment
    else:
        if runtime_root is None or hook_python is None:
            raise HostSetupError(
                "hook runtime and hook Python must be supplied together"
            )
        selected_runtime, selected_python, rendered, merger = _load_codex_hook_fragment(
            runtime_root, hook_python
        )
    hooks_path = codex_home / "hooks.json"
    _ensure_regular_target(hooks_path)
    hooks_original = hooks_path.read_bytes() if hooks_path.exists() else None
    existing: dict[str, Any] = {}
    if hooks_original is not None:
        try:
            loaded = json.loads(hooks_original.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HostSetupError(
                f"Codex hooks file is invalid JSON: {hooks_path}"
            ) from exc
        if not isinstance(loaded, dict):
            raise HostSetupError(f"Codex hooks file must be an object: {hooks_path}")
        existing = loaded
    strip_fragment = dict(rendered)
    strip_fragment["payload"] = {}
    try:
        merged = merger(existing, strip_fragment)
    except Exception as exc:
        raise HostSetupError(f"Agent Hook Runtime rejected Codex hooks: {exc}") from exc
    if not isinstance(merged, dict):
        raise HostSetupError("Agent Hook Runtime merger must return a JSON object")
    required = rendered.get("required_top_level", {})
    if isinstance(required, dict):
        for key, value in required.items():
            if key not in existing and merged.get(key) == value:
                merged.pop(key, None)
    target = rendered.get("merge_target")
    if (
        isinstance(target, str)
        and target not in existing
        and merged.get(target) in ({}, [])
    ):
        merged.pop(target, None)
    return CodexHookPlan(
        hooks_path=hooks_path,
        hooks_original=hooks_original,
        hook_config_path=Path("."),
        hook_config_original=None,
        hook_config_content=b"",
        memory_root=Path("."),
        selected_python=selected_python,
        selected_runtime=selected_runtime,
        merged=merged,
        builtin=builtin,
        config_path=config_path.resolve(),
    )


def _apply_codex_hook_strip(plan: CodexHookPlan) -> dict[str, object]:
    if plan.hooks_original is None:
        return _json_result(
            "no_op",
            path=str(plan.hooks_path),
            reason="Codex hooks file was not found",
        )
    live_hooks = plan.hooks_path.read_bytes() if plan.hooks_path.exists() else None
    if live_hooks != plan.hooks_original:
        raise HostSetupError(f"write conflict while updating {plan.hooks_path}")
    try:
        existing = json.loads(plan.hooks_original.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(
            f"Codex hooks file is invalid JSON: {plan.hooks_path}"
        ) from exc
    if existing == plan.merged:
        encoded = plan.hooks_original
    else:
        encoded = (json.dumps(plan.merged, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    status, backup = _atomic_write(
        plan.hooks_path,
        encoded,
        expected_original=plan.hooks_original,
    )
    return _json_result(status, path=str(plan.hooks_path), backup=backup)


def _prepare_codex_rules_removal(
    codex_home: Path,
    *,
    legacy_contract_path: Path | None = None,
) -> tuple[Path, bytes | None, bytes]:
    legacy = load_legacy_contract(legacy_contract_path)
    target, original, existing = _select_codex_rules_candidate(codex_home)
    if original is None:
        return target, None, b""
    removed = remove_managed_contract(existing, source=str(target), legacy=legacy)
    verified_target, verified_original, verified_existing = (
        _select_codex_rules_candidate(codex_home)
    )
    if (
        verified_target != target
        or verified_original != original
        or verified_existing != existing
    ):
        raise HostSetupError("Codex rules candidates changed during uninstall")
    return target, original, removed.encode("utf-8")


def _apply_codex_rules_removal(
    plan: tuple[Path, bytes | None, bytes],
) -> dict[str, object]:
    target, original, content = plan
    if original is None:
        return _json_result(
            "no_op",
            path=str(target),
            reason="global rules file was not found",
        )
    status, backup = _atomic_write(target, content, expected_original=original)
    return _json_result(status, path=str(target), backup=backup)


def remove_codex_rules(
    codex_home: Path,
    *,
    legacy_contract_path: Path | None = None,
) -> dict[str, object]:
    return _apply_codex_rules_removal(
        _prepare_codex_rules_removal(
            codex_home, legacy_contract_path=legacy_contract_path
        )
    )


def _prepare_codex_mcp_removal(
    codex_home: Path,
    *,
    codex_binary: Path | None = None,
) -> CodexMcpPlan:
    selected_codex = codex_binary or (
        Path(found).resolve() if (found := shutil.which("codex")) else None
    )
    if (
        selected_codex is None
        or not selected_codex.is_file()
        or not os.access(selected_codex, os.X_OK)
    ):
        raise HostSetupError("Codex CLI could not be located")
    codex_config = codex_home / "config.toml"
    _ensure_regular_target(codex_config)
    config_original = codex_config.read_bytes() if codex_config.exists() else None
    current = _run_codex(
        selected_codex, codex_home, ["mcp", "get", "keepygaga", "--json"]
    )
    current_payload: Mapping[str, Any] | None = None
    if current.returncode == 0:
        try:
            loaded_payload = json.loads(current.stdout)
        except json.JSONDecodeError as exc:
            raise HostSetupError(
                "Codex returned invalid MCP registration JSON"
            ) from exc
        if not isinstance(loaded_payload, Mapping):
            raise HostSetupError("Codex returned an invalid MCP registration object")
        current_payload = loaded_payload
    elif "No MCP server named" not in f"{current.stderr}\n{current.stdout}":
        detail = (
            current.stderr.strip() or current.stdout.strip() or "unknown Codex error"
        )
        raise HostSetupError(f"Codex MCP registration could not be read: {detail}")
    return CodexMcpPlan(
        codex_home=codex_home,
        codex_config=codex_config,
        config_original=config_original,
        selected_python=Path(sys.executable),
        selected_args=(),
        selected_codex=selected_codex,
        desired_env={},
        current_payload=current_payload,
        needs_update=current_payload is not None,
    )


def _apply_codex_mcp_removal(plan: CodexMcpPlan) -> dict[str, object]:
    if not plan.needs_update:
        current = _run_codex(
            plan.selected_codex,
            plan.codex_home,
            ["mcp", "get", "keepygaga", "--json"],
        )
        if current.returncode == 0:
            raise HostSetupError("Keepygaga MCP registration changed after preflight")
        if "No MCP server named" not in f"{current.stderr}\n{current.stdout}":
            detail = (
                current.stderr.strip()
                or current.stdout.strip()
                or "unknown Codex error"
            )
            raise HostSetupError(
                f"Codex MCP registration could not be re-read: {detail}"
            )
        return _json_result("no_op", key="keepygaga")
    live_config = plan.codex_config.read_bytes() if plan.codex_config.exists() else None
    if live_config != plan.config_original:
        raise HostSetupError(f"write conflict while updating {plan.codex_config}")
    config_backup = (
        _exclusive_backup(plan.codex_config, plan.config_original)
        if plan.config_original is not None
        else None
    )
    removed = _run_codex(
        plan.selected_codex,
        plan.codex_home,
        ["mcp", "remove", "keepygaga"],
    )
    if removed.returncode != 0:
        detail = (
            removed.stderr.strip() or removed.stdout.strip() or "unknown Codex error"
        )
        raise HostSetupError(f"Codex MCP removal failed: {detail}")
    recovery: dict[str, object] = (
        {
            "action": "restore_file",
            "source": str(config_backup),
            "destination": str(plan.codex_config),
        }
        if config_backup is not None
        else {
            "action": "manual_restore_required",
            "reason": "Keepygaga MCP registration was not removed",
        }
    )
    try:
        verified = _run_codex(
            plan.selected_codex,
            plan.codex_home,
            ["mcp", "get", "keepygaga", "--json"],
        )
    except HostSetupError as exc:
        raise HostSetupPartialError(
            f"Codex accepted the MCP removal but verification failed: {exc}",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    verified=False,
                    backup=str(config_backup) if config_backup else None,
                    recovery=recovery,
                )
            },
        ) from exc
    if verified.returncode == 0 or (
        "No MCP server named" not in f"{verified.stderr}\n{verified.stdout}"
    ):
        detail = (
            verified.stderr.strip() or verified.stdout.strip() or "unknown Codex error"
        )
        raise HostSetupPartialError(
            f"Codex accepted the MCP removal but verification failed: {detail}",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    verified=False,
                    backup=str(config_backup) if config_backup else None,
                    recovery=recovery,
                )
            },
        )
    return _json_result(
        "applied",
        key="keepygaga",
        backup=str(config_backup) if config_backup else None,
    )


def uninstall_codex_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    codex_home: Path | None = None,
    codex_binary: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    del config
    selected_home = _resolve_codex_home(codex_home, create=False)
    if not selected_home.exists():
        skipped = _json_result(
            "no_op", reason="Codex home was not found", path=str(selected_home)
        )
        return _json_result(
            "no_op",
            host="codex",
            version=__version__,
            rules=skipped,
            mcp=skipped,
            hooks=skipped,
            restart_required=True,
        )
    lock = FileLock(str(selected_home / ".keepygaga-host-setup.lock"), timeout=30)
    components: dict[str, object] = {}
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"Codex setup lock could not be acquired: {exc}") from exc
    try:
        try:
            hook_plan = _prepare_codex_hook_strip(
                selected_home,
                hook_runtime,
                hook_python,
                config_path=config_path,
                hook_config_path=hook_config_path,
            )
            mcp_plan = _prepare_codex_mcp_removal(
                selected_home, codex_binary=codex_binary
            )
            rules_plan = _prepare_codex_rules_removal(selected_home)
            components["rules"] = _apply_codex_rules_removal(rules_plan)
            components["hooks"] = _apply_codex_hook_strip(hook_plan)
            components["mcp"] = _apply_codex_mcp_removal(mcp_plan)
        except HostSetupPartialError as exc:
            components.update(exc.components)
            raise HostSetupPartialError(str(exc), components) from exc
        except Exception as exc:
            if any(
                isinstance(value, Mapping) and value.get("status") == "applied"
                for value in components.values()
            ):
                raise HostSetupPartialError(str(exc), components) from exc
            if isinstance(exc, HostSetupError):
                raise
            raise HostSetupError(str(exc)) from exc
    finally:
        lock.release()
    rules = components["rules"]
    mcp = components["mcp"]
    hooks = components["hooks"]
    component_statuses = {rules["status"], mcp["status"], hooks["status"]}
    overall = "applied" if "applied" in component_statuses else "no_op"
    return _json_result(
        overall,
        host="codex",
        version=__version__,
        rules=rules,
        mcp=mcp,
        hooks=hooks,
        restart_required=True,
    )
