from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, NoReturn

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from keepygaga import __version__
from keepygaga.config import KeepygagaConfig
from keepygaga.hooks import build_fragment, merge_hook_fragment
from keepygaga.host_common import (
    HOOK_ENTRYPOINTS,
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
    remove_managed_contract,
    render_fragment,
    run_captured,
    validate_hook_command_path,
    validate_host_source,
)
from keepygaga.launchers import resolve_launcher

_atomic_write = atomic_write
_default_hook_config_path = default_hook_config_path
_ensure_regular_target = ensure_regular_target
_exclusive_backup = exclusive_backup
_json_result = json_result
_load_hook_merger = load_hook_merger
_probe_hook_python = probe_hook_python
_probe_keepygaga_python = probe_keepygaga_python
_render_fragment = render_fragment
_validate_hook_command_path = validate_hook_command_path


def _yaml_runtime() -> Any:
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    return yaml


@dataclass(frozen=True)
class FilePlan:
    path: Path
    original: bytes | None
    content: bytes


@dataclass(frozen=True)
class McpInvocation:
    command: Path
    args: tuple[str, ...]


@dataclass(frozen=True)
class ExistingJsonMcpPlan:
    path: Path
    original: bytes | None
    update: FilePlan | None


@dataclass(frozen=True)
class JsonHostSpec:
    host: str
    default_home: str
    rules_relative: Path
    mcp_path: Callable[[Path], Path]
    hook_relative: Path
    hook_fragment: str
    mcp_fields: Mapping[str, object]
    legacy_mcp_path: Callable[[Path], Path] | None = None


@dataclass(frozen=True)
class HookSelection:
    fragment: dict[str, Any]
    merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    runtime_config: FilePlan | None
    runtime_root: Path
    hook_python: Path


@dataclass(frozen=True)
class GrokMcpPlan:
    binary: Path
    home: Path
    config_path: Path
    config_original: bytes | None
    invocation: McpInvocation
    desired_env: dict[str, str]
    needs_update: bool


@dataclass(frozen=True)
class HermesConfigPlan:
    file: FilePlan
    mcp_changed: bool
    hooks_changed: bool


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for key, value in pairs:
        if key in loaded:
            raise _DuplicateJsonKeyError(key)
        loaded[key] = value
    return loaded


def _ensure_workbuddy_legacy_home(legacy_home: Path) -> None:
    try:
        if legacy_home.is_symlink() or legacy_home.is_junction():
            raise HostSetupError(
                f"workbuddy legacy home must not be a link: {legacy_home}"
            )
        if legacy_home.exists() and not legacy_home.is_dir():
            raise HostSetupError(
                f"workbuddy legacy home is not a directory: {legacy_home}"
            )
    except OSError as exc:
        raise HostSetupError(
            f"workbuddy legacy home could not be inspected: {legacy_home}"
        ) from exc


def _workbuddy_legacy_mcp_path(home: Path) -> Path:
    legacy_home = home.parent / ".codebuddy"
    _ensure_workbuddy_legacy_home(legacy_home)
    return legacy_home / ".mcp.json"


CLAUDE_CODE = JsonHostSpec(
    host="claude-code",
    default_home=".claude",
    rules_relative=Path("CLAUDE.md"),
    mcp_path=lambda home: home.parent / ".claude.json",
    hook_relative=Path("settings.json"),
    hook_fragment="claude",
    mcp_fields={"type": "stdio"},
)

WORKBUDDY = JsonHostSpec(
    host="workbuddy",
    default_home=".workbuddy",
    rules_relative=Path("CODEBUDDY.md"),
    mcp_path=lambda home: home / "mcp.json",
    hook_relative=Path("settings.json"),
    hook_fragment="workbuddy",
    mcp_fields={"type": "stdio"},
    legacy_mcp_path=_workbuddy_legacy_mcp_path,
)

ANTIGRAVITY = JsonHostSpec(
    host="antigravity",
    default_home=".gemini",
    rules_relative=Path("AGENTS.md"),
    mcp_path=lambda home: home / "config" / "mcp_config.json",
    hook_relative=Path("config/hooks.json"),
    hook_fragment="antigravity",
    mcp_fields={},
)


_validated_source = validate_host_source


def _resolve_home(
    selected: Path | None, default_name: str, label: str, *, create: bool = True
) -> Path:
    raw = selected.expanduser() if selected is not None else Path.home() / default_name
    if not raw.is_absolute():
        raise HostSetupError(f"{label} home must be an absolute path: {raw}")
    if raw.is_symlink():
        raise HostSetupError(f"{label} home must not be a symlink: {raw}")
    home = raw.resolve()
    if home.exists() and not home.is_dir():
        raise HostSetupError(f"{label} home is not a directory: {home}")
    if create:
        try:
            home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HostSetupError(f"{label} home could not be created: {exc}") from exc
    return home


def _select_python(python: Path | None) -> Path:
    selected = Path(os.path.abspath((python or Path(sys.executable)).expanduser()))
    if not selected.is_file():
        raise HostSetupError(f"Keepygaga Python does not exist: {selected}")
    _probe_keepygaga_python(selected)
    return selected


def _select_mcp_invocation(python: Path | None) -> McpInvocation:
    if python is not None:
        selected_python = _select_python(python)
        return McpInvocation(selected_python, ("-m", "keepygaga.server"))
    try:
        return McpInvocation(resolve_launcher("keepygaga-mcp"), ())
    except RuntimeError as exc:
        raise HostSetupError(str(exc)) from exc


def _load_json_object(path: Path) -> tuple[bytes | None, dict[str, Any]]:
    _ensure_regular_target(path)
    if not path.exists():
        return None, {}
    try:
        original = path.read_bytes()
        loaded = json.loads(
            original.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
    except _DuplicateJsonKeyError as exc:
        raise HostSetupError(
            f"host config contains duplicate JSON key {exc.args[0]!r}: {path}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(f"host config is invalid JSON: {path}") from exc
    if not isinstance(loaded, dict):
        raise HostSetupError(f"host config must be a JSON object: {path}")
    return original, loaded


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _load_yaml_object(path: Path) -> tuple[bytes | None, dict[str, Any]]:
    from ruamel.yaml.error import YAMLError

    _ensure_regular_target(path)
    if not path.exists():
        return None, {}
    try:
        original = path.read_bytes()
        loaded = _yaml_runtime().load(original.decode("utf-8"))
    except (OSError, UnicodeError, YAMLError) as exc:
        raise HostSetupError(f"host config is invalid YAML: {path}") from exc
    if loaded is None:
        return original, {}
    if not isinstance(loaded, dict):
        raise HostSetupError(f"host config must be a YAML mapping: {path}")
    return original, loaded


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    rendered = StringIO()
    _yaml_runtime().dump(value, rendered)
    return rendered.getvalue().encode("utf-8")


def _plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_data(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_plain_data(nested) for nested in value]
    return value


def _apply_file(plan: FilePlan) -> dict[str, object]:
    status, backup = _atomic_write(
        plan.path, plan.content, expected_original=plan.original
    )
    return _json_result(status, path=str(plan.path), backup=backup)


def _prepare_rules(path: Path) -> FilePlan:
    _ensure_regular_target(path)
    try:
        original = path.read_bytes() if path.exists() else None
    except OSError as exc:
        raise HostSetupError(f"global rules could not be read: {path}") from exc
    try:
        existing = original.decode("utf-8") if original is not None else ""
    except UnicodeError as exc:
        raise HostSetupError(f"global rules are not valid UTF-8: {path}") from exc
    merged = merge_managed_contract(
        existing,
        load_canonical_contract(),
        source=str(path),
        legacy=load_legacy_contract(),
    )
    return FilePlan(path, original, merged.encode("utf-8"))


def _updated_mcp_entry(
    current: object,
    *,
    invocation: McpInvocation,
    config_path: Path,
    fixed_fields: Mapping[str, object],
) -> dict[str, Any]:
    if current is None:
        entry: dict[str, Any] = {}
    elif isinstance(current, Mapping):
        entry = {key: current[key] for key in ("print",) if key in current}
    else:
        raise HostSetupError("existing Keepygaga MCP registration must be an object")
    raw_environment = current.get("env", {}) if isinstance(current, Mapping) else {}
    if not isinstance(raw_environment, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_environment.items()
    ):
        raise HostSetupError("existing Keepygaga MCP environment is invalid")
    supported_environment = {"KEEPYGAGA_CONFIG", "KEEPYGAGA_WRITER"}
    environment = {
        key: value
        for key, value in raw_environment.items()
        if key in supported_environment
    }
    environment["KEEPYGAGA_CONFIG"] = str(config_path.resolve())
    entry.update(fixed_fields)
    entry.update(
        {
            "command": str(invocation.command),
            "args": list(invocation.args),
            "env": environment,
        }
    )
    return entry


def _prepare_json_mcp(
    path: Path,
    *,
    invocation: McpInvocation,
    config_path: Path,
    fixed_fields: Mapping[str, object],
) -> FilePlan:
    original, loaded = _load_json_object(path)
    servers = loaded.get("mcpServers")
    if servers is None:
        server_map: dict[str, Any] = {}
    elif isinstance(servers, Mapping):
        server_map = dict(servers)
    else:
        raise HostSetupError(f"mcpServers must be an object: {path}")
    matching_keys = [
        key
        for key in server_map
        if isinstance(key, str) and key.casefold() == "keepygaga"
    ]
    if len(matching_keys) > 1:
        raise HostSetupError(
            f"multiple case-insensitive Keepygaga MCP registrations: {path}"
        )
    current_key = matching_keys[0] if matching_keys else "keepygaga"
    server_map["keepygaga"] = _updated_mcp_entry(
        server_map.get(current_key),
        invocation=invocation,
        config_path=config_path,
        fixed_fields=fixed_fields,
    )
    if current_key != "keepygaga":
        server_map.pop(current_key)
    merged = {**loaded, "mcpServers": server_map}
    content = _json_bytes(merged)
    if merged == loaded and original is not None:
        content = original
    return FilePlan(path, original, content)


def _prepare_existing_json_mcp(
    path: Path,
    *,
    invocation: McpInvocation,
    config_path: Path,
    fixed_fields: Mapping[str, object],
) -> ExistingJsonMcpPlan:
    original, loaded = _load_json_object(path)
    if original is None:
        return ExistingJsonMcpPlan(path, None, None)
    servers = loaded.get("mcpServers")
    if servers is None:
        return ExistingJsonMcpPlan(path, original, None)
    if not isinstance(servers, Mapping):
        raise HostSetupError(f"mcpServers must be an object: {path}")
    server_map = dict(servers)
    matching_keys = [
        key
        for key in server_map
        if isinstance(key, str) and key.casefold() == "keepygaga"
    ]
    if not matching_keys:
        return ExistingJsonMcpPlan(path, original, None)
    if len(matching_keys) != 1:
        raise HostSetupError(
            f"multiple case-insensitive Keepygaga MCP registrations: {path}"
        )
    current_key = matching_keys[0]
    server_map["keepygaga"] = _legacy_mcp_entry(
        server_map[current_key],
        invocation=invocation,
        config_path=config_path,
        fixed_fields=fixed_fields,
    )
    if current_key != "keepygaga":
        server_map.pop(current_key)
    merged = {**loaded, "mcpServers": server_map}
    normalized_disabled = _normalized_disabled_servers(loaded, path)
    if normalized_disabled is not None:
        merged["disabledMcpServers"] = normalized_disabled
    content = _json_bytes(merged)
    if merged == loaded and original is not None:
        content = original
    return ExistingJsonMcpPlan(path, original, FilePlan(path, original, content))


def _legacy_mcp_entry(
    current: object,
    *,
    invocation: McpInvocation,
    config_path: Path,
    fixed_fields: Mapping[str, object],
) -> dict[str, object]:
    updated = _updated_mcp_entry(
        current,
        invocation=invocation,
        config_path=config_path,
        fixed_fields=fixed_fields,
    )
    raw_environment = updated["env"]
    assert isinstance(raw_environment, dict)
    environment = {"KEEPYGAGA_CONFIG": raw_environment["KEEPYGAGA_CONFIG"]}
    writer = raw_environment.get("KEEPYGAGA_WRITER")
    if isinstance(writer, str):
        environment["KEEPYGAGA_WRITER"] = writer
    updated["env"] = environment
    updated["args"] = ["-I", "-m", "keepygaga.server"] if invocation.args else []
    updated.pop("cwd", None)
    return updated


def _normalized_disabled_servers(
    loaded: Mapping[str, Any], path: Path
) -> list[str] | None:
    disabled_servers = loaded.get("disabledMcpServers")
    if disabled_servers is None:
        return None
    if not isinstance(disabled_servers, list) or not all(
        isinstance(key, str) for key in disabled_servers
    ):
        raise HostSetupError(f"disabledMcpServers must be a string list: {path}")
    normalized: list[str] = []
    for key in disabled_servers:
        canonical = "keepygaga" if key.casefold() == "keepygaga" else key
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _apply_existing_json_mcp(plan: ExistingJsonMcpPlan) -> dict[str, object]:
    _ensure_workbuddy_legacy_home(plan.path.parent)
    _ensure_regular_target(plan.path)
    try:
        live = plan.path.read_bytes() if plan.path.exists() else None
    except OSError as exc:
        raise HostSetupError(f"host config could not be read: {plan.path}") from exc
    if live != plan.original:
        raise HostSetupError(f"write conflict while updating {plan.path}")
    if plan.update is None:
        return _json_result(
            "skipped",
            path=str(plan.path),
            reason="legacy Keepygaga registration was not found",
        )
    return _apply_file(plan.update)


def _select_hook_runtime(runtime_root: Path, hook_python: Path) -> tuple[Path, Path]:
    raw_runtime = runtime_root.expanduser()
    if raw_runtime.is_symlink():
        raise HostSetupError(
            f"Agent Hook Runtime root must not be a symlink: {raw_runtime}"
        )
    runtime = raw_runtime.resolve()
    selected_python = Path(os.path.abspath(hook_python.expanduser()))
    if not runtime.is_dir():
        raise HostSetupError(f"Agent Hook Runtime root is invalid: {runtime}")
    if not selected_python.is_file():
        raise HostSetupError(f"Hook Python is invalid: {selected_python}")
    _probe_hook_python(selected_python)
    _validate_hook_command_path(runtime, label="Agent Hook Runtime root")
    _validate_hook_command_path(selected_python, label="Hook Python")
    for relative in HOOK_ENTRYPOINTS:
        entrypoint = runtime / relative
        if entrypoint.is_symlink() or not entrypoint.is_file():
            raise HostSetupError(
                f"Agent Hook Runtime entrypoint is missing: {entrypoint}"
            )
    return runtime, selected_python


def _render_host_hook_fragment(
    host: str, runtime: Path, selected_python: Path
) -> dict[str, Any]:
    fragment_path = runtime / "config" / "hooks" / f"{host}.json"
    if fragment_path.is_symlink():
        raise HostSetupError(
            f"Agent Hook Runtime fragment must not be a symlink: {fragment_path}"
        )
    try:
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostSetupError(
            f"Agent Hook Runtime fragment could not be loaded: {fragment_path}"
        ) from exc
    if not isinstance(fragment, dict) or fragment.get("host") != host:
        raise HostSetupError(f"Agent Hook Runtime {host} fragment is invalid")
    rendered = _render_fragment(
        fragment,
        {"{{PYTHON}}": str(selected_python), "{{RUNTIME_ROOT}}": str(runtime)},
    )
    if not isinstance(rendered, dict):
        raise HostSetupError(f"rendered {host} Hook fragment is invalid")
    markers = rendered.get("owned_command_markers")
    if not isinstance(markers, list):
        raise HostSetupError(f"rendered {host} Hook ownership markers are invalid")
    markers.extend(str(runtime / relative) for relative in HOOK_ENTRYPOINTS)
    return rendered


def _load_hook_runtime(
    host: str,
    runtime_root: Path,
    hook_python: Path,
) -> tuple[
    dict[str, Any],
    Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    Path,
    Path,
]:
    runtime, selected_python = _select_hook_runtime(runtime_root, hook_python)
    rendered = _render_host_hook_fragment(host, runtime, selected_python)
    return rendered, _load_hook_merger(runtime), runtime, selected_python


def _hook_material_for_removal(
    host: str,
    config_path: Path,
    runtime_root: Path | None,
    hook_python: Path | None,
) -> tuple[dict[str, Any], Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]]:
    if runtime_root is not None or hook_python is not None:
        if runtime_root is None or hook_python is None:
            raise HostSetupError(
                "hook runtime and hook Python must be supplied together"
            )
        fragment, merger, _runtime, _python = _load_hook_runtime(
            host, runtime_root, hook_python
        )
        return fragment, merger
    try:
        launcher = resolve_launcher("keepygaga")
    except RuntimeError as exc:
        raise HostSetupError(str(exc)) from exc
    return (
        build_fragment(
            host,
            launcher=launcher,
            config_path=config_path.resolve(),
            enabled=False,
        ),
        merge_hook_fragment,
    )


def _prepare_hook_selection(
    host: str,
    memory_root: Path,
    runtime_root: Path | None,
    hook_python: Path | None,
    *,
    config_path: Path,
    hook_config_path: Path | None,
) -> HookSelection:
    if runtime_root is None and hook_python is None:
        try:
            launcher = resolve_launcher("keepygaga")
        except RuntimeError as exc:
            raise HostSetupError(str(exc)) from exc
        fragment = build_fragment(
            host,
            launcher=launcher,
            config_path=config_path.resolve(),
        )
        return HookSelection(
            fragment=fragment,
            merger=merge_hook_fragment,
            runtime_config=None,
            runtime_root=Path(__file__).resolve().parent / "hooks",
            hook_python=Path(sys.executable).resolve(),
        )
    if runtime_root is None or hook_python is None:
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    rendered, merger, runtime, selected_python = _load_hook_runtime(
        host, runtime_root, hook_python
    )
    default_config = _default_hook_config_path()
    selected_config = (
        Path(os.path.abspath(hook_config_path.expanduser()))
        if hook_config_path is not None
        else default_config
    )
    if selected_config != default_config:
        raise HostSetupError(
            "selected Hook config is not the path Agent Hook Runtime will load; "
            "set AGENT_HOOK_RUNTIME_CONFIG to the same absolute path"
        )
    configured_environment_root = os.environ.get(
        "AGENT_HOOK_RUNTIME_MEMORY_ROOT", ""
    ).strip()
    if configured_environment_root:
        raw_environment_root = Path(configured_environment_root).expanduser()
        if not raw_environment_root.is_absolute():
            raise HostSetupError("AGENT_HOOK_RUNTIME_MEMORY_ROOT must be absolute")
        environment_root = raw_environment_root.resolve()
        if environment_root != memory_root:
            raise HostSetupError(
                "AGENT_HOOK_RUNTIME_MEMORY_ROOT conflicts with configured memory.root"
            )
    runtime_original, runtime_content = prepare_hook_runtime_config(
        selected_config, memory_root
    )
    return HookSelection(
        fragment=rendered,
        merger=merger,
        runtime_config=FilePlan(selected_config, runtime_original, runtime_content),
        runtime_root=runtime,
        hook_python=selected_python,
    )


def _prepare_json_hooks(path: Path, selection: HookSelection) -> FilePlan:
    original, existing = _load_json_object(path)
    try:
        merged = selection.merger(existing, selection.fragment)
    except Exception as exc:
        raise HostSetupError(f"Agent Hook Runtime rejected host hooks: {exc}") from exc
    if not isinstance(merged, dict):
        raise HostSetupError("Agent Hook Runtime merger must return a JSON object")
    content = _json_bytes(merged)
    if merged == existing and original is not None:
        content = original
    return FilePlan(path, original, content)


def _apply_hooks(host_plan: FilePlan, selection: HookSelection) -> dict[str, object]:
    parts: dict[str, object] = {}
    try:
        if selection.runtime_config is not None:
            parts["runtime_config"] = _apply_file(selection.runtime_config)
        host = _apply_file(host_plan)
        parts["host_config"] = host
    except Exception as exc:
        if _has_applied_component(parts):
            raise HostSetupPartialError(
                f"Hook setup partially applied: {exc}",
                {"hooks": _json_result("applied", **parts)},
            ) from exc
        if isinstance(exc, HostSetupError):
            raise
        raise HostSetupError(str(exc)) from exc
    return _json_result(_component_status(parts), **parts)


def _has_applied_component(components: Mapping[str, object]) -> bool:
    return any(
        isinstance(value, Mapping) and value.get("status") == "applied"
        for value in components.values()
    )


def _component_status(components: Mapping[str, object]) -> str:
    return "applied" if _has_applied_component(components) else "no_op"


def _raise_component_failure(
    exc: Exception, components: dict[str, object]
) -> NoReturn:
    if isinstance(exc, HostSetupPartialError):
        components.update(exc.components)
        raise HostSetupPartialError(str(exc), components) from exc
    if _has_applied_component(components):
        raise HostSetupPartialError(str(exc), components) from exc
    if isinstance(exc, HostSetupError):
        raise exc
    raise HostSetupError(str(exc)) from exc


def _run_components(
    *,
    host: str,
    doctor: Mapping[str, object],
    mcp_plan: FilePlan,
    rules_plan: FilePlan,
    hooks_plan: FilePlan | None,
    hook_selection: HookSelection | None,
    legacy_mcp_plan: ExistingJsonMcpPlan | None = None,
) -> dict[str, object]:
    components: dict[str, object] = {}
    try:
        components["mcp"] = _apply_file(mcp_plan)
        if legacy_mcp_plan is not None:
            components["legacy_mcp"] = _apply_existing_json_mcp(legacy_mcp_plan)
        components["rules"] = _apply_file(rules_plan)
        components["hooks"] = (
            _apply_hooks(hooks_plan, hook_selection)
            if hooks_plan is not None and hook_selection is not None
            else _json_result(
                "skipped", reason="compatible Agent Hook Runtime was not selected"
            )
        )
    except Exception as exc:
        _raise_component_failure(exc, components)
    return _json_result(
        _component_status(components),
        host=host,
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        **components,
        restart_required=True,
    )


def _setup_json_host(
    spec: JsonHostSpec,
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None,
    python: Path | None,
    hook_runtime: Path | None,
    hook_python: Path | None,
    hook_config_path: Path | None,
) -> dict[str, object]:
    memory_root, doctor = _validated_source(config_path, config)
    home = _resolve_home(host_home, spec.default_home, spec.host)
    invocation = _select_mcp_invocation(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(
            f"{spec.host} setup lock could not be acquired: {exc}"
        ) from exc
    try:
        selection = _prepare_hook_selection(
            spec.hook_fragment,
            memory_root,
            hook_runtime,
            hook_python,
            config_path=config_path,
            hook_config_path=hook_config_path,
        )
        mcp = _prepare_json_mcp(
            spec.mcp_path(home),
            invocation=invocation,
            config_path=config_path,
            fixed_fields=spec.mcp_fields,
        )
        legacy_mcp = (
            _prepare_existing_json_mcp(
                spec.legacy_mcp_path(home),
                invocation=invocation,
                config_path=config_path,
                fixed_fields=spec.mcp_fields,
            )
            if spec.legacy_mcp_path is not None
            else None
        )
        rules = _prepare_rules(home / spec.rules_relative)
        hooks = _prepare_json_hooks(home / spec.hook_relative, selection)
        return _run_components(
            host=spec.host,
            doctor=doctor,
            mcp_plan=mcp,
            rules_plan=rules,
            hooks_plan=hooks,
            hook_selection=selection,
            legacy_mcp_plan=legacy_mcp,
        )
    finally:
        lock.release()


def setup_claude_code_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _setup_json_host(
        CLAUDE_CODE,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def setup_workbuddy_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _setup_json_host(
        WORKBUDDY,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def setup_antigravity_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _setup_json_host(
        ANTIGRAVITY,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def _run_grok(
    binary: Path, home: Path, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(home.parent)
    try:
        return run_captured(
            [str(binary), *arguments],
            timeout=30,
            env=environment,
            cwd=home.parent,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"Grok CLI could not be executed: {exc}") from exc


def _grok_registrations(binary: Path, home: Path) -> list[Mapping[str, Any]]:
    listed = _run_grok(binary, home, ["mcp", "list", "--json"])
    if listed.returncode != 0:
        raise HostSetupError(
            f"Grok MCP registrations could not be read (exit {listed.returncode})"
        )
    try:
        payload = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        raise HostSetupError("Grok returned invalid MCP registration JSON") from exc
    if not isinstance(payload, list):
        raise HostSetupError("Grok returned an invalid MCP registration list")
    return [item for item in payload if isinstance(item, Mapping)]


def _matching_grok_registration(
    registration: Mapping[str, Any],
    invocation: McpInvocation,
    environment: Mapping[str, str],
) -> bool:
    return (
        registration.get("name") == "keepygaga"
        and registration.get("scope") == "user"
        and registration.get("enabled") is True
        and registration.get("command") == str(invocation.command)
        and registration.get("args") == list(invocation.args)
        and registration.get("env") == dict(environment)
    )


def _single_grok_registration(
    registrations: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    matching = [
        item
        for item in registrations
        if item.get("name") == "keepygaga" and item.get("scope") == "user"
    ]
    if len(matching) > 1:
        raise HostSetupError("Grok returned duplicate user Keepygaga registrations")
    return matching[0] if matching else None


def _prepare_grok_mcp(
    home: Path,
    config_path: Path,
    *,
    invocation: McpInvocation,
    grok_binary: Path | None,
) -> GrokMcpPlan:
    selected_binary = grok_binary or (
        Path(found).resolve() if (found := shutil.which("grok")) else None
    )
    if (
        selected_binary is None
        or not selected_binary.is_file()
        or not os.access(selected_binary, os.X_OK)
    ):
        raise HostSetupError("Grok CLI could not be located")
    config_file = home / "config.toml"
    _ensure_regular_target(config_file)
    try:
        original = config_file.read_bytes() if config_file.exists() else None
    except OSError as exc:
        raise HostSetupError(f"Grok config could not be read: {config_file}") from exc
    current = _single_grok_registration(_grok_registrations(selected_binary, home))
    raw_environment = current.get("env", {}) if current is not None else {}
    if not isinstance(raw_environment, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_environment.items()
    ):
        raise HostSetupError("existing Grok Keepygaga MCP environment is invalid")
    supported_environment = {"KEEPYGAGA_CONFIG", "KEEPYGAGA_WRITER"}
    if set(raw_environment) - supported_environment:
        raise HostSetupError(
            "existing Grok Keepygaga MCP registration has additional environment "
            "variables that cannot be safely passed through the Grok CLI"
        )
    desired_environment = dict(raw_environment)
    desired_environment["KEEPYGAGA_CONFIG"] = str(config_path.resolve())
    needs_update = current is None or not _matching_grok_registration(
        current, invocation, desired_environment
    )
    return GrokMcpPlan(
        binary=selected_binary,
        home=home,
        config_path=config_file,
        config_original=original,
        invocation=invocation,
        desired_env=desired_environment,
        needs_update=needs_update,
    )


def _apply_grok_mcp(plan: GrokMcpPlan) -> dict[str, object]:
    if not plan.needs_update:
        current = _single_grok_registration(_grok_registrations(plan.binary, plan.home))
        if current is None or not _matching_grok_registration(
            current, plan.invocation, plan.desired_env
        ):
            raise HostSetupError("Grok MCP registration changed after preflight")
        return _json_result("no_op", key="keepygaga", path=str(plan.config_path))
    try:
        live = plan.config_path.read_bytes() if plan.config_path.exists() else None
    except OSError as exc:
        raise HostSetupError(
            f"Grok config could not be re-read: {plan.config_path}"
        ) from exc
    if live != plan.config_original:
        raise HostSetupError(f"write conflict while updating {plan.config_path}")
    backup = (
        _exclusive_backup(plan.config_path, plan.config_original)
        if plan.config_original is not None
        else None
    )
    environment_arguments = [
        value
        for key in sorted(plan.desired_env)
        for value in ("--env", f"{key}={plan.desired_env[key]}")
    ]
    added = _run_grok(
        plan.binary,
        plan.home,
        [
            "mcp",
            "add",
            "--scope",
            "user",
            *environment_arguments,
            "keepygaga",
            "--",
            str(plan.invocation.command),
            *plan.invocation.args,
        ],
    )
    if added.returncode != 0:
        raise HostSetupError(f"Grok MCP registration failed (exit {added.returncode})")
    try:
        current = _single_grok_registration(_grok_registrations(plan.binary, plan.home))
        if current is None or not _matching_grok_registration(
            current, plan.invocation, plan.desired_env
        ):
            raise HostSetupError(
                "Grok MCP registration does not match the requested transport"
            )
    except HostSetupError as exc:
        recovery: dict[str, object] = (
            {
                "action": "restore_file",
                "source": str(backup),
                "destination": str(plan.config_path),
            }
            if backup is not None
            else {
                "action": "remove_new_registration",
                "command": "grok mcp remove --scope user keepygaga",
            }
        )
        raise HostSetupPartialError(
            f"Grok accepted the MCP update but verification failed: {exc}",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    path=str(plan.config_path),
                    verified=False,
                    backup=str(backup) if backup else None,
                    recovery=recovery,
                )
            },
        ) from exc
    return _json_result(
        "applied",
        key="keepygaga",
        path=str(plan.config_path),
        backup=str(backup) if backup else None,
    )


def _grok_rules_path(home: Path) -> Path:
    try:
        by_name = {
            entry.name: entry
            for entry in home.iterdir()
            if entry.name in {"AGENTS.md", "Agents.md"}
        }
    except OSError as exc:
        raise HostSetupError(f"Grok home could not be inspected: {home}") from exc
    title_case = by_name.get("Agents.md")
    upper_case = by_name.get("AGENTS.md")
    if title_case is None and upper_case is None:
        return home / "Agents.md"
    if title_case is None:
        return upper_case  # type: ignore[return-value]
    try:
        same_file = upper_case is not None and os.path.samefile(title_case, upper_case)
    except OSError as exc:
        raise HostSetupError("Grok global rules could not be compared") from exc
    if upper_case is None or same_file:
        return title_case

    managed: list[Path] = []
    for candidate in (title_case, upper_case):
        try:
            existing = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise HostSetupError(
                f"could not read Grok global rules: {candidate}"
            ) from exc
        if parse_managed_block(existing, source=str(candidate)) is not None:
            managed.append(candidate)
    if len(managed) > 1:
        raise HostSetupError("Grok global rules contain duplicate Keepygaga blocks")
    return managed[0] if managed else title_case


def setup_grok_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    grok_binary: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    _memory_root, doctor = _validated_source(config_path, config)
    del hook_config_path
    home = _resolve_home(host_home, ".grok", "grok")
    if home.name != ".grok":
        raise HostSetupError(
            "Grok home must be named .grok so its CLI uses the same config"
        )
    invocation = _select_mcp_invocation(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"grok setup lock could not be acquired: {exc}") from exc
    components: dict[str, object] = {}
    try:
        fragment, merger = _hook_material_for_removal(
            "grok", config_path, hook_runtime, hook_python
        )
        mcp_plan = _prepare_grok_mcp(
            home,
            config_path,
            invocation=invocation,
            grok_binary=grok_binary,
        )
        rules_plan = _prepare_rules(_grok_rules_path(home))
        hooks_path = home / "hooks" / "keepygaga.json"
        hooks_plan = _prepare_json_hooks_removal(hooks_path, fragment, merger)
        legacy_hooks_plan = _prepare_json_hooks_removal(
            home / "hooks" / "agent-hook-runtime.json",
            fragment,
            merger,
        )
        try:
            components["mcp"] = _apply_grok_mcp(mcp_plan)
            components["rules"] = _apply_file(rules_plan)
            hooks_result = (
                _apply_file(hooks_plan)
                if hooks_plan is not None
                else _json_result(
                    "no_op",
                    path=str(hooks_path),
                    reason="Grok closeout uses the managed Agent Contract",
                )
            )
            components["hooks"] = {**hooks_result, "mode": "rules_fallback"}
            components["legacy_hooks"] = (
                _apply_file(legacy_hooks_plan)
                if legacy_hooks_plan is not None
                else _absent_component(
                    home / "hooks" / "agent-hook-runtime.json",
                    kind="legacy hooks file",
                )
            )
        except Exception as exc:
            _raise_component_failure(exc, components)
    finally:
        lock.release()
    return _json_result(
        _component_status(components),
        host="grok",
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        **components,
        restart_required=True,
    )


def _prepare_hermes_config(
    path: Path,
    *,
    invocation: McpInvocation,
    config_path: Path,
    hook_selection: HookSelection | None,
) -> HermesConfigPlan:
    original, loaded = _load_yaml_object(path)
    merged = deepcopy(loaded)
    raw_servers = merged.get("mcp_servers")
    if raw_servers is None:
        merged["mcp_servers"] = {}
        servers = merged["mcp_servers"]
    elif isinstance(raw_servers, MutableMapping):
        servers = raw_servers
    else:
        raise HostSetupError(f"mcp_servers must be a mapping: {path}")
    previous_mcp = deepcopy(servers.get("keepygaga"))
    servers["keepygaga"] = _updated_mcp_entry(
        servers.get("keepygaga"),
        invocation=invocation,
        config_path=config_path,
        fixed_fields={},
    )
    mcp_changed = previous_mcp != servers["keepygaga"]
    hooks_changed = False
    if hook_selection is not None:
        before_hooks = deepcopy(merged.get("hooks"))
        try:
            hook_merged = hook_selection.merger(
                _plain_data(merged), hook_selection.fragment
            )
        except Exception as exc:
            raise HostSetupError(
                f"Agent Hook Runtime rejected Hermes hooks: {exc}"
            ) from exc
        if not isinstance(hook_merged, dict):
            raise HostSetupError("Agent Hook Runtime merger must return a mapping")
        desired_hooks = hook_merged.get("hooks")
        if before_hooks is None and desired_hooks in ({}, []):
            desired_hooks = None
        hooks_changed = _plain_data(before_hooks) != _plain_data(desired_hooks)
        if hooks_changed:
            if desired_hooks is None:
                merged.pop("hooks", None)
            else:
                merged["hooks"] = desired_hooks
    content = _yaml_bytes(merged)
    if not mcp_changed and not hooks_changed and original is not None:
        content = original
    return HermesConfigPlan(
        file=FilePlan(path, original, content),
        mcp_changed=mcp_changed,
        hooks_changed=hooks_changed,
    )


def setup_hermes_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    memory_root, doctor = _validated_source(config_path, config)
    home = _resolve_home(host_home, ".hermes", "hermes")
    invocation = _select_mcp_invocation(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"hermes setup lock could not be acquired: {exc}") from exc
    components: dict[str, object] = {}
    try:
        selection = _prepare_hook_selection(
            "hermes",
            memory_root,
            hook_runtime,
            hook_python,
            config_path=config_path,
            hook_config_path=hook_config_path,
        )
        config_plan = _prepare_hermes_config(
            home / "config.yaml",
            invocation=invocation,
            config_path=config_path,
            hook_selection=selection,
        )
        rules_plan = _prepare_rules(home / "SOUL.md")
        try:
            host_config = _apply_file(config_plan.file)
            host_applied = host_config["status"] == "applied"
            components["mcp"] = _json_result(
                "applied" if host_applied and config_plan.mcp_changed else "no_op",
                key="keepygaga",
                path=str(config_plan.file.path),
                backup=host_config.get("backup") if config_plan.mcp_changed else None,
            )
            components["hooks"] = _json_result(
                "applied" if host_applied and config_plan.hooks_changed else "no_op",
                host_config={
                    "status": (
                        "applied"
                        if host_applied and config_plan.hooks_changed
                        else "no_op"
                    ),
                    "path": str(config_plan.file.path),
                    "backup": (
                        host_config.get("backup") if config_plan.hooks_changed else None
                    ),
                },
                approval_required=config_plan.hooks_changed,
            )
            components["rules"] = _apply_file(rules_plan)
            if selection.runtime_config is not None:
                runtime = _apply_file(selection.runtime_config)
                hook_result = components["hooks"]
                if not isinstance(hook_result, dict):
                    raise HostSetupError("Hermes Hook result is invalid")
                hook_result["runtime_config"] = runtime
                if runtime["status"] == "applied":
                    hook_result["status"] = "applied"
        except Exception as exc:
            if _has_applied_component(components):
                raise HostSetupPartialError(str(exc), components) from exc
            if isinstance(exc, HostSetupError):
                raise
            raise HostSetupError(str(exc)) from exc
    finally:
        lock.release()
    return _json_result(
        _component_status(components),
        host="hermes",
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        **components,
        restart_required=True,
    )


def _prepare_rules_removal(path: Path) -> FilePlan | None:
    _ensure_regular_target(path)
    if not path.exists():
        return None
    try:
        original = path.read_bytes()
        existing = original.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(f"global rules could not be read: {path}") from exc
    removed = remove_managed_contract(
        existing,
        source=str(path),
        legacy=load_legacy_contract(),
    )
    content = removed.encode("utf-8")
    if content == original:
        content = original
    return FilePlan(path, original, content)


def _prepare_json_mcp_removal(path: Path) -> FilePlan | None:
    original, loaded = _load_json_object(path)
    if original is None:
        return None
    servers = loaded.get("mcpServers")
    merged = dict(loaded)
    changed = False
    if servers is None:
        server_map: dict[str, Any] | None = None
    elif not isinstance(servers, Mapping):
        raise HostSetupError(f"mcpServers must be an object: {path}")
    else:
        server_map = dict(servers)
        matching_keys = [
            key
            for key in server_map
            if isinstance(key, str) and key.casefold() == "keepygaga"
        ]
        if len(matching_keys) > 1:
            raise HostSetupError(
                f"multiple case-insensitive Keepygaga MCP registrations: {path}"
            )
        if matching_keys:
            server_map.pop(matching_keys[0])
            merged["mcpServers"] = server_map
            changed = True
    disabled_servers = loaded.get("disabledMcpServers")
    if disabled_servers is not None:
        if not isinstance(disabled_servers, list) or not all(
            isinstance(key, str) for key in disabled_servers
        ):
            raise HostSetupError(f"disabledMcpServers must be a string list: {path}")
        normalized_disabled = [
            key for key in disabled_servers if key.casefold() != "keepygaga"
        ]
        if normalized_disabled != list(disabled_servers):
            merged["disabledMcpServers"] = normalized_disabled
            changed = True
    if not changed:
        return FilePlan(path, original, original)
    return FilePlan(path, original, _json_bytes(merged))


def _prepare_existing_json_mcp_removal(path: Path) -> ExistingJsonMcpPlan:
    original, loaded = _load_json_object(path)
    if original is None:
        return ExistingJsonMcpPlan(path, None, None)
    update = _prepare_json_mcp_removal(path)
    if update is None or update.content == original:
        return ExistingJsonMcpPlan(path, original, None)
    return ExistingJsonMcpPlan(path, original, update)


def _without_empty_hook_target(
    existing: Mapping[str, Any],
    merged: dict[str, Any],
    fragment: Mapping[str, Any],
) -> dict[str, Any]:
    target = fragment.get("merge_target")
    if not isinstance(target, str) or not target:
        return merged
    if target in existing:
        return merged
    added = merged.get(target)
    if added in ({}, []):
        cleaned = dict(merged)
        cleaned.pop(target, None)
        return cleaned
    return merged


def _prepare_json_hooks_removal(
    path: Path,
    fragment: Mapping[str, Any],
    merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> FilePlan | None:
    original, existing = _load_json_object(path)
    if original is None:
        return None
    strip_fragment = dict(fragment)
    strip_fragment["payload"] = {}
    try:
        merged = merger(existing, strip_fragment)
    except Exception as exc:
        raise HostSetupError(f"Agent Hook Runtime rejected host hooks: {exc}") from exc
    if not isinstance(merged, dict):
        raise HostSetupError("Agent Hook Runtime merger must return a JSON object")
    merged = _without_empty_hook_target(existing, merged, strip_fragment)
    if merged == existing:
        return FilePlan(path, original, original)
    return FilePlan(path, original, _json_bytes(merged))


def _absent_component(path: Path, *, kind: str) -> dict[str, object]:
    return _json_result("no_op", path=str(path), reason=f"{kind} was not found")


def _run_uninstall_components(
    *,
    host: str,
    mcp_plan: FilePlan | None,
    rules_plan: FilePlan | None,
    hooks_plan: FilePlan | None,
    hooks_selected: bool,
    legacy_mcp_plan: ExistingJsonMcpPlan | None = None,
    mcp_path: Path,
    rules_path: Path,
    hooks_path: Path,
) -> dict[str, object]:
    components: dict[str, object] = {}
    try:
        components["hooks"] = (
            _apply_file(hooks_plan)
            if hooks_plan is not None
            else (
                _json_result(
                    "skipped", reason="compatible Agent Hook Runtime was not selected"
                )
                if not hooks_selected
                else _absent_component(hooks_path, kind="hooks file")
            )
        )
        components["rules"] = (
            _apply_file(rules_plan)
            if rules_plan is not None
            else _absent_component(rules_path, kind="global rules file")
        )
        if legacy_mcp_plan is not None:
            components["legacy_mcp"] = _apply_existing_json_mcp(legacy_mcp_plan)
        components["mcp"] = (
            _apply_file(mcp_plan)
            if mcp_plan is not None
            else _absent_component(mcp_path, kind="MCP config")
        )
    except Exception as exc:
        _raise_component_failure(exc, components)
    return _json_result(
        _component_status(components),
        host=host,
        version=__version__,
        **components,
        restart_required=True,
    )


def _uninstall_json_host(
    spec: JsonHostSpec,
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None,
    python: Path | None,
    hook_runtime: Path | None,
    hook_python: Path | None,
    hook_config_path: Path | None,
) -> dict[str, object]:
    del config, python, hook_config_path
    home = _resolve_home(host_home, spec.default_home, spec.host, create=False)
    lock = None
    if home.exists():
        lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
        try:
            lock.acquire()
        except (FileLockTimeout, OSError) as exc:
            raise HostSetupError(
                f"{spec.host} setup lock could not be acquired: {exc}"
            ) from exc
    try:
        fragment, merger = _hook_material_for_removal(
            spec.hook_fragment, config_path, hook_runtime, hook_python
        )
        mcp_path = spec.mcp_path(home)
        rules_path = home / spec.rules_relative
        hooks_path = home / spec.hook_relative
        mcp = _prepare_json_mcp_removal(mcp_path)
        legacy_mcp = (
            _prepare_existing_json_mcp_removal(spec.legacy_mcp_path(home))
            if spec.legacy_mcp_path is not None
            else None
        )
        rules = _prepare_rules_removal(rules_path)
        hooks = _prepare_json_hooks_removal(hooks_path, fragment, merger)
        return _run_uninstall_components(
            host=spec.host,
            mcp_plan=mcp,
            rules_plan=rules,
            hooks_plan=hooks,
            hooks_selected=fragment is not None,
            legacy_mcp_plan=legacy_mcp,
            mcp_path=mcp_path,
            rules_path=rules_path,
            hooks_path=hooks_path,
        )
    finally:
        if lock is not None:
            lock.release()


def uninstall_claude_code_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _uninstall_json_host(
        CLAUDE_CODE,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def uninstall_workbuddy_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _uninstall_json_host(
        WORKBUDDY,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def uninstall_antigravity_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    return _uninstall_json_host(
        ANTIGRAVITY,
        config_path,
        config,
        host_home=host_home,
        python=python,
        hook_runtime=hook_runtime,
        hook_python=hook_python,
        hook_config_path=hook_config_path,
    )


def _prepare_grok_mcp_removal(
    home: Path,
    *,
    grok_binary: Path | None,
) -> GrokMcpPlan:
    selected_binary = grok_binary or (
        Path(found).resolve() if (found := shutil.which("grok")) else None
    )
    if (
        selected_binary is None
        or not selected_binary.is_file()
        or not os.access(selected_binary, os.X_OK)
    ):
        raise HostSetupError("Grok CLI could not be located")
    config_file = home / "config.toml"
    _ensure_regular_target(config_file)
    try:
        original = config_file.read_bytes() if config_file.exists() else None
    except OSError as exc:
        raise HostSetupError(f"Grok config could not be read: {config_file}") from exc
    registrations = [
        item
        for item in _grok_registrations(selected_binary, home)
        if item.get("name") == "keepygaga" and item.get("scope") == "user"
    ]
    if len(registrations) > 1:
        raise HostSetupError("Grok returned duplicate user Keepygaga registrations")
    return GrokMcpPlan(
        binary=selected_binary,
        home=home,
        config_path=config_file,
        config_original=original,
        invocation=McpInvocation(Path(sys.executable), ()),
        desired_env={},
        needs_update=bool(registrations),
    )


def _apply_grok_mcp_removal(plan: GrokMcpPlan) -> dict[str, object]:
    if not plan.needs_update:
        registrations = [
            item
            for item in _grok_registrations(plan.binary, plan.home)
            if item.get("name") == "keepygaga" and item.get("scope") == "user"
        ]
        if registrations:
            raise HostSetupError("Grok MCP registration changed after preflight")
        return _json_result("no_op", key="keepygaga", path=str(plan.config_path))
    try:
        live = plan.config_path.read_bytes() if plan.config_path.exists() else None
    except OSError as exc:
        raise HostSetupError(
            f"Grok config could not be re-read: {plan.config_path}"
        ) from exc
    if live != plan.config_original:
        raise HostSetupError(f"write conflict while updating {plan.config_path}")
    backup = (
        _exclusive_backup(plan.config_path, plan.config_original)
        if plan.config_original is not None
        else None
    )
    removed = _run_grok(
        plan.binary,
        plan.home,
        ["mcp", "remove", "--scope", "user", "keepygaga"],
    )
    if removed.returncode != 0:
        raise HostSetupError(f"Grok MCP removal failed (exit {removed.returncode})")
    recovery: dict[str, object] = (
        {
            "action": "restore_file",
            "source": str(backup),
            "destination": str(plan.config_path),
        }
        if backup is not None
        else {
            "action": "manual_restore_required",
            "reason": "Keepygaga MCP registration was not removed",
        }
    )
    try:
        remaining = [
            item
            for item in _grok_registrations(plan.binary, plan.home)
            if item.get("name") == "keepygaga" and item.get("scope") == "user"
        ]
    except HostSetupError as exc:
        raise HostSetupPartialError(
            f"Grok accepted the MCP removal but verification failed: {exc}",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    path=str(plan.config_path),
                    verified=False,
                    backup=str(backup) if backup else None,
                    recovery=recovery,
                )
            },
        ) from exc
    if remaining:
        raise HostSetupPartialError(
            "Grok accepted the MCP removal but verification failed",
            {
                "mcp": _json_result(
                    "applied",
                    key="keepygaga",
                    path=str(plan.config_path),
                    verified=False,
                    backup=str(backup) if backup else None,
                    recovery=recovery,
                )
            },
        )
    return _json_result(
        "applied",
        key="keepygaga",
        path=str(plan.config_path),
        backup=str(backup) if backup else None,
    )


def uninstall_grok_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    grok_binary: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    del config, python, hook_config_path
    home = _resolve_home(host_home, ".grok", "grok", create=False)
    if home.name != ".grok":
        raise HostSetupError(
            "Grok home must be named .grok so its CLI uses the same config"
        )
    lock = None
    if home.exists():
        lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
        try:
            lock.acquire()
        except (FileLockTimeout, OSError) as exc:
            raise HostSetupError(
                f"grok setup lock could not be acquired: {exc}"
            ) from exc
    components: dict[str, object] = {}
    try:
        fragment, merger = _hook_material_for_removal(
            "grok", config_path, hook_runtime, hook_python
        )
        mcp_plan = (
            _prepare_grok_mcp_removal(home, grok_binary=grok_binary)
            if home.exists()
            else None
        )
        rules_path = _grok_rules_path(home) if home.exists() else home / "Agents.md"
        rules_plan = _prepare_rules_removal(rules_path) if home.exists() else None
        hooks_path = home / "hooks" / "keepygaga.json"
        hooks_plan = _prepare_json_hooks_removal(hooks_path, fragment, merger)
        legacy_hooks_path = home / "hooks" / "agent-hook-runtime.json"
        legacy_hooks_plan = _prepare_json_hooks_removal(
            legacy_hooks_path, fragment, merger
        )
        try:
            components["hooks"] = (
                _apply_file(hooks_plan)
                if hooks_plan is not None
                else (
                    _json_result(
                        "skipped",
                        reason="compatible Agent Hook Runtime was not selected",
                    )
                    if fragment is None
                    else _absent_component(hooks_path, kind="hooks file")
                )
            )
            components["legacy_hooks"] = (
                _apply_file(legacy_hooks_plan)
                if legacy_hooks_plan is not None
                else _absent_component(legacy_hooks_path, kind="legacy hooks file")
            )
            components["rules"] = (
                _apply_file(rules_plan)
                if rules_plan is not None
                else _absent_component(rules_path, kind="global rules file")
            )
            components["mcp"] = (
                _apply_grok_mcp_removal(mcp_plan)
                if mcp_plan is not None
                else _json_result(
                    "no_op",
                    key="keepygaga",
                    path=str(home / "config.toml"),
                    reason="Grok home was not found",
                )
            )
        except Exception as exc:
            _raise_component_failure(exc, components)
    finally:
        if lock is not None:
            lock.release()
    return _json_result(
        _component_status(components),
        host="grok",
        version=__version__,
        **components,
        restart_required=True,
    )


def _remove_hermes_mcp(merged: MutableMapping[str, Any], path: Path) -> bool:
    raw_servers = merged.get("mcp_servers")
    if isinstance(raw_servers, MutableMapping) and any(
        isinstance(key, str) and key.casefold() == "keepygaga" for key in raw_servers
    ):
        matching = [
            key
            for key in list(raw_servers)
            if isinstance(key, str) and key.casefold() == "keepygaga"
        ]
        if len(matching) > 1:
            raise HostSetupError(
                f"multiple case-insensitive Keepygaga MCP registrations: {path}"
            )
        raw_servers.pop(matching[0])
        return True
    elif raw_servers is not None and not isinstance(raw_servers, MutableMapping):
        raise HostSetupError(f"mcp_servers must be a mapping: {path}")
    return False


def _remove_hermes_hooks(
    merged: MutableMapping[str, Any],
    fragment: Mapping[str, Any] | None,
    merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None,
) -> bool:
    if fragment is None or merger is None:
        return False
    before_hooks = deepcopy(merged.get("hooks"))
    strip_fragment = dict(fragment)
    strip_fragment["payload"] = {}
    try:
        hook_merged = merger(_plain_data(merged), strip_fragment)
    except Exception as exc:
        raise HostSetupError(
            f"Agent Hook Runtime rejected Hermes hooks: {exc}"
        ) from exc
    if not isinstance(hook_merged, dict):
        raise HostSetupError("Agent Hook Runtime merger must return a mapping")
    desired_hooks = hook_merged.get("hooks")
    if before_hooks is None and desired_hooks in ({}, []):
        desired_hooks = None
    changed = _plain_data(before_hooks) != _plain_data(desired_hooks)
    if changed and desired_hooks is None:
        merged.pop("hooks", None)
    elif changed:
        merged["hooks"] = desired_hooks
    return changed


def _prepare_hermes_config_removal(
    path: Path,
    *,
    fragment: Mapping[str, Any] | None,
    merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None,
) -> HermesConfigPlan | None:
    original, loaded = _load_yaml_object(path)
    if original is None:
        return None
    merged = deepcopy(loaded)
    mcp_changed = _remove_hermes_mcp(merged, path)
    hooks_changed = _remove_hermes_hooks(merged, fragment, merger)
    content = _yaml_bytes(merged)
    if not mcp_changed and not hooks_changed and original is not None:
        content = original
    return HermesConfigPlan(
        file=FilePlan(path, original, content),
        mcp_changed=mcp_changed,
        hooks_changed=hooks_changed,
    )


def uninstall_hermes_host(
    config_path: Path,
    config: KeepygagaConfig,
    *,
    host_home: Path | None = None,
    python: Path | None = None,
    hook_runtime: Path | None = None,
    hook_python: Path | None = None,
    hook_config_path: Path | None = None,
) -> dict[str, object]:
    del config, python, hook_config_path
    home = _resolve_home(host_home, ".hermes", "hermes", create=False)
    lock = None
    if home.exists():
        lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
        try:
            lock.acquire()
        except (FileLockTimeout, OSError) as exc:
            raise HostSetupError(
                f"hermes setup lock could not be acquired: {exc}"
            ) from exc
    components: dict[str, object] = {}
    try:
        fragment, merger = _hook_material_for_removal(
            "hermes", config_path, hook_runtime, hook_python
        )
        config_plan = _prepare_hermes_config_removal(
            home / "config.yaml",
            fragment=fragment,
            merger=merger,
        )
        rules_plan = _prepare_rules_removal(home / "SOUL.md")
        try:
            components["rules"] = (
                _apply_file(rules_plan)
                if rules_plan is not None
                else _absent_component(home / "SOUL.md", kind="global rules file")
            )
            if config_plan is None:
                components["mcp"] = _absent_component(
                    home / "config.yaml", kind="Hermes config"
                )
                components["hooks"] = (
                    _json_result(
                        "skipped",
                        reason="compatible Agent Hook Runtime was not selected",
                    )
                    if fragment is None
                    else _absent_component(home / "config.yaml", kind="Hermes config")
                )
            else:
                host_config = _apply_file(config_plan.file)
                host_applied = host_config["status"] == "applied"
                components["mcp"] = _json_result(
                    "applied" if host_applied and config_plan.mcp_changed else "no_op",
                    key="keepygaga",
                    path=str(config_plan.file.path),
                    backup=(
                        host_config.get("backup") if config_plan.mcp_changed else None
                    ),
                )
                if fragment is None:
                    components["hooks"] = _json_result(
                        "skipped",
                        reason="compatible Agent Hook Runtime was not selected",
                    )
                else:
                    components["hooks"] = _json_result(
                        "applied"
                        if host_applied and config_plan.hooks_changed
                        else "no_op",
                        host_config={
                            "status": (
                                "applied"
                                if host_applied and config_plan.hooks_changed
                                else "no_op"
                            ),
                            "path": str(config_plan.file.path),
                            "backup": (
                                host_config.get("backup")
                                if config_plan.hooks_changed
                                else None
                            ),
                        },
                    )
        except Exception as exc:
            if _has_applied_component(components):
                raise HostSetupPartialError(str(exc), components) from exc
            if isinstance(exc, HostSetupError):
                raise
            raise HostSetupError(str(exc)) from exc
    finally:
        if lock is not None:
            lock.release()
    return _json_result(
        _component_status(components),
        host="hermes",
        version=__version__,
        **components,
        restart_required=True,
    )
