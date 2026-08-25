from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from keepygaga import __version__
from keepygaga.config import KeepygagaConfig
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
    render_fragment,
    validate_hook_command_path,
    validate_host_source,
)

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
class JsonHostSpec:
    host: str
    default_home: str
    rules_relative: Path
    mcp_path: Callable[[Path], Path]
    hook_relative: Path
    hook_fragment: str
    mcp_fields: Mapping[str, object]


@dataclass(frozen=True)
class HookSelection:
    fragment: dict[str, Any]
    merger: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    runtime_config: FilePlan
    runtime_root: Path
    hook_python: Path


@dataclass(frozen=True)
class GrokMcpPlan:
    binary: Path
    home: Path
    config_path: Path
    config_original: bytes | None
    python: Path
    desired_env: dict[str, str]
    needs_update: bool


@dataclass(frozen=True)
class HermesConfigPlan:
    file: FilePlan
    mcp_changed: bool
    hooks_changed: bool


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


def _resolve_home(selected: Path | None, default_name: str, label: str) -> Path:
    raw = selected.expanduser() if selected is not None else Path.home() / default_name
    if not raw.is_absolute():
        raise HostSetupError(f"{label} home must be an absolute path: {raw}")
    if raw.is_symlink():
        raise HostSetupError(f"{label} home must not be a symlink: {raw}")
    home = raw.resolve()
    if home.exists() and not home.is_dir():
        raise HostSetupError(f"{label} home is not a directory: {home}")
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


def _load_json_object(path: Path) -> tuple[bytes | None, dict[str, Any]]:
    _ensure_regular_target(path)
    if not path.exists():
        return None, {}
    try:
        original = path.read_bytes()
        loaded = json.loads(original.decode("utf-8"))
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
    python: Path,
    config_path: Path,
    fixed_fields: Mapping[str, object],
) -> dict[str, Any]:
    if current is None:
        entry: dict[str, Any] = {}
    elif isinstance(current, Mapping):
        entry = dict(current)
    else:
        raise HostSetupError("existing Keepygaga MCP registration must be an object")
    for field in (
        "auth",
        "auth_type",
        "headers",
        "httpUrl",
        "oauth",
        "serverUrl",
        "transport",
        "url",
    ):
        entry.pop(field, None)
    if "type" not in fixed_fields:
        entry.pop("type", None)
    raw_environment = entry.get("env", {})
    if not isinstance(raw_environment, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_environment.items()
    ):
        raise HostSetupError("existing Keepygaga MCP environment is invalid")
    environment = dict(raw_environment)
    environment["KEEPYGAGA_CONFIG"] = str(config_path.resolve())
    entry.update(fixed_fields)
    entry.update(
        {
            "command": str(python),
            "args": ["-m", "keepygaga.server"],
            "env": environment,
        }
    )
    return entry


def _prepare_json_mcp(
    path: Path,
    *,
    python: Path,
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
    server_map["keepygaga"] = _updated_mcp_entry(
        server_map.get("keepygaga"),
        python=python,
        config_path=config_path,
        fixed_fields=fixed_fields,
    )
    merged = {**loaded, "mcpServers": server_map}
    content = _json_bytes(merged)
    if merged == loaded and original is not None:
        content = original
    return FilePlan(path, original, content)


def _prepare_hook_selection(
    host: str,
    memory_root: Path,
    runtime_root: Path,
    hook_python: Path,
    *,
    hook_config_path: Path | None,
) -> HookSelection:
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
    merger = _load_hook_merger(runtime)

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
        runtime = _apply_file(selection.runtime_config)
        parts["runtime_config"] = runtime
        host = _apply_file(host_plan)
        parts["host_config"] = host
    except Exception as exc:
        if any(
            isinstance(value, Mapping) and value.get("status") == "applied"
            for value in parts.values()
        ):
            raise HostSetupPartialError(
                f"Hook setup partially applied: {exc}",
                {"hooks": _json_result("applied", **parts)},
            ) from exc
        if isinstance(exc, HostSetupError):
            raise
        raise HostSetupError(str(exc)) from exc
    status = (
        "applied"
        if any(
            isinstance(value, Mapping) and value.get("status") == "applied"
            for value in parts.values()
        )
        else "no_op"
    )
    return _json_result(status, **parts)


def _run_components(
    *,
    host: str,
    doctor: Mapping[str, object],
    mcp_plan: FilePlan,
    rules_plan: FilePlan,
    hooks_plan: FilePlan | None,
    hook_selection: HookSelection | None,
) -> dict[str, object]:
    components: dict[str, object] = {}
    try:
        components["mcp"] = _apply_file(mcp_plan)
        components["rules"] = _apply_file(rules_plan)
        components["hooks"] = (
            _apply_hooks(hooks_plan, hook_selection)
            if hooks_plan is not None and hook_selection is not None
            else _json_result(
                "skipped", reason="compatible Agent Hook Runtime was not selected"
            )
        )
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
    statuses = {
        value.get("status")
        for value in components.values()
        if isinstance(value, Mapping)
    }
    return _json_result(
        "applied" if "applied" in statuses else "no_op",
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
    if (hook_runtime is None) != (hook_python is None):
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    memory_root, doctor = _validated_source(config_path, config)
    home = _resolve_home(host_home, spec.default_home, spec.host)
    selected_python = _select_python(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(
            f"{spec.host} setup lock could not be acquired: {exc}"
        ) from exc
    try:
        selection = (
            _prepare_hook_selection(
                spec.hook_fragment,
                memory_root,
                hook_runtime,
                hook_python,
                hook_config_path=hook_config_path,
            )
            if hook_runtime is not None and hook_python is not None
            else None
        )
        mcp = _prepare_json_mcp(
            spec.mcp_path(home),
            python=selected_python,
            config_path=config_path,
            fixed_fields=spec.mcp_fields,
        )
        rules = _prepare_rules(home / spec.rules_relative)
        hooks = (
            _prepare_json_hooks(home / spec.hook_relative, selection)
            if selection is not None
            else None
        )
        return _run_components(
            host=spec.host,
            doctor=doctor,
            mcp_plan=mcp,
            rules_plan=rules,
            hooks_plan=hooks,
            hook_selection=selection,
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
        return subprocess.run(
            [str(binary), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            cwd=home.parent,
            timeout=30,
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
    registration: Mapping[str, Any], python: Path, environment: Mapping[str, str]
) -> bool:
    return (
        registration.get("name") == "keepygaga"
        and registration.get("scope") == "user"
        and registration.get("enabled") is True
        and registration.get("command") == str(python)
        and registration.get("args") == ["-m", "keepygaga.server"]
        and registration.get("env") == dict(environment)
    )


def _prepare_grok_mcp(
    home: Path,
    config_path: Path,
    *,
    python: Path,
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
    current = registrations[0] if registrations else None
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
        current, python, desired_environment
    )
    return GrokMcpPlan(
        binary=selected_binary,
        home=home,
        config_path=config_file,
        config_original=original,
        python=python,
        desired_env=desired_environment,
        needs_update=needs_update,
    )


def _apply_grok_mcp(plan: GrokMcpPlan) -> dict[str, object]:
    if not plan.needs_update:
        registrations = _grok_registrations(plan.binary, plan.home)
        current = next(
            (
                item
                for item in registrations
                if item.get("name") == "keepygaga" and item.get("scope") == "user"
            ),
            None,
        )
        if current is None or not _matching_grok_registration(
            current, plan.python, plan.desired_env
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
            str(plan.python),
            "-m",
            "keepygaga.server",
        ],
    )
    if added.returncode != 0:
        raise HostSetupError(f"Grok MCP registration failed (exit {added.returncode})")
    try:
        current = next(
            (
                item
                for item in _grok_registrations(plan.binary, plan.home)
                if item.get("name") == "keepygaga" and item.get("scope") == "user"
            ),
            None,
        )
        if current is None or not _matching_grok_registration(
            current, plan.python, plan.desired_env
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
    if (hook_runtime is None) != (hook_python is None):
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    memory_root, doctor = _validated_source(config_path, config)
    home = _resolve_home(host_home, ".grok", "grok")
    if home.name != ".grok":
        raise HostSetupError(
            "Grok home must be named .grok so its CLI uses the same config"
        )
    selected_python = _select_python(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"grok setup lock could not be acquired: {exc}") from exc
    components: dict[str, object] = {}
    try:
        selection = (
            _prepare_hook_selection(
                "grok",
                memory_root,
                hook_runtime,
                hook_python,
                hook_config_path=hook_config_path,
            )
            if hook_runtime is not None and hook_python is not None
            else None
        )
        mcp_plan = _prepare_grok_mcp(
            home,
            config_path,
            python=selected_python,
            grok_binary=grok_binary,
        )
        rules_plan = _prepare_rules(_grok_rules_path(home))
        hooks_plan = (
            _prepare_json_hooks(home / "hooks" / "agent-hook-runtime.json", selection)
            if selection is not None
            else None
        )
        try:
            components["mcp"] = _apply_grok_mcp(mcp_plan)
            components["rules"] = _apply_file(rules_plan)
            components["hooks"] = (
                _apply_hooks(hooks_plan, selection)
                if hooks_plan is not None and selection is not None
                else _json_result(
                    "skipped", reason="compatible Agent Hook Runtime was not selected"
                )
            )
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
    statuses = {
        value.get("status")
        for value in components.values()
        if isinstance(value, Mapping)
    }
    return _json_result(
        "applied" if "applied" in statuses else "no_op",
        host="grok",
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        **components,
        restart_required=True,
    )


def _prepare_hermes_config(
    path: Path,
    *,
    python: Path,
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
        python=python,
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
        hooks_changed = before_hooks != desired_hooks
        if hooks_changed:
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
    if (hook_runtime is None) != (hook_python is None):
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    memory_root, doctor = _validated_source(config_path, config)
    home = _resolve_home(host_home, ".hermes", "hermes")
    selected_python = _select_python(python)
    lock = FileLock(str(home / ".keepygaga-host-setup.lock"), timeout=30)
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"hermes setup lock could not be acquired: {exc}") from exc
    components: dict[str, object] = {}
    try:
        selection = (
            _prepare_hook_selection(
                "hermes",
                memory_root,
                hook_runtime,
                hook_python,
                hook_config_path=hook_config_path,
            )
            if hook_runtime is not None and hook_python is not None
            else None
        )
        config_plan = _prepare_hermes_config(
            home / "config.yaml",
            python=selected_python,
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
            if selection is None:
                components["hooks"] = _json_result(
                    "skipped", reason="compatible Agent Hook Runtime was not selected"
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
                    approval_required=config_plan.hooks_changed,
                )
            components["rules"] = _apply_file(rules_plan)
            if selection is not None:
                runtime = _apply_file(selection.runtime_config)
                hook_result = components["hooks"]
                if not isinstance(hook_result, dict):
                    raise HostSetupError("Hermes Hook result is invalid")
                hook_result["runtime_config"] = runtime
                if runtime["status"] == "applied":
                    hook_result["status"] = "applied"
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
    statuses = {
        value.get("status")
        for value in components.values()
        if isinstance(value, Mapping)
    }
    return _json_result(
        "applied" if "applied" in statuses else "no_op",
        host="hermes",
        version=__version__,
        doctor=doctor.get("status", "unknown"),
        **components,
        restart_required=True,
    )
