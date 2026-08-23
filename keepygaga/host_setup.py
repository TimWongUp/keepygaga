from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from keepygaga import __version__
from keepygaga.config import PROJECT_ROOT, KeepygagaConfig
from keepygaga.diagnostics import run_doctor

START_MARKER = "<!-- KEEPYGAGA:START -->"
END_MARKER = "<!-- KEEPYGAGA:END -->"
VERSION_PREFIX = "<!-- KEEPYGAGA:VERSION:"
CONTRACT_RELATIVE_PATH = Path("docs/agent-contract.md")
LEGACY_CONTRACT_RELATIVE_PATH = Path("docs/legacy-agent-contract-v0.md")
HOOK_FRAGMENT_RELATIVE_PATH = Path("config/hooks/codex.json")
HOOK_MERGER_RELATIVE_PATH = Path("agent_hook_runtime/hook_config.py")
HOOK_ENTRYPOINTS = (
    "hooks/context_hook.py",
    "hooks/memory_route_hook.py",
    "hooks/closeout_hook.py",
)
_EXPECTED_ANY = object()


class HostSetupError(RuntimeError):
    pass


class HostSetupPartialError(HostSetupError):
    def __init__(self, message: str, components: Mapping[str, object]) -> None:
        super().__init__(message)
        self.components = dict(components)


@dataclass(frozen=True)
class ManagedBlock:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class CodexHookPlan:
    hooks_path: Path
    hooks_original: bytes | None
    hook_config_path: Path
    memory_root: Path
    selected_python: Path
    selected_runtime: Path
    merged: dict[str, Any]


@dataclass(frozen=True)
class CodexMcpPlan:
    codex_home: Path
    codex_config: Path
    config_original: bytes | None
    selected_python: Path
    selected_codex: Path
    desired_env: dict[str, str]
    current_payload: Mapping[str, Any] | None
    needs_update: bool


def _json_result(status: str, **values: object) -> dict[str, object]:
    return {"status": status, **values}


def _contract_path() -> Path:
    source_path = PROJECT_ROOT / CONTRACT_RELATIVE_PATH
    if source_path.is_file():
        return source_path

    try:
        files = importlib.metadata.files("keepygaga") or ()
    except importlib.metadata.PackageNotFoundError as exc:
        raise HostSetupError("installed Agent Contract could not be located") from exc
    for entry in files:
        normalized = entry.as_posix()
        if normalized.endswith("share/keepygaga/agent-contract.md"):
            located = Path(entry.locate()).resolve()
            if located.is_file():
                return located
    raise HostSetupError("installed Agent Contract could not be located")


def _legacy_contract_path() -> Path:
    source_path = PROJECT_ROOT / LEGACY_CONTRACT_RELATIVE_PATH
    if source_path.is_file():
        return source_path
    try:
        files = importlib.metadata.files("keepygaga") or ()
    except importlib.metadata.PackageNotFoundError as exc:
        raise HostSetupError(
            "installed legacy Agent Contract could not be located"
        ) from exc
    for entry in files:
        if entry.as_posix().endswith("share/keepygaga/legacy-agent-contract-v0.md"):
            located = Path(entry.locate()).resolve()
            if located.is_file():
                return located
    raise HostSetupError("installed legacy Agent Contract could not be located")


def _line_ranges(text: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        ranges.append((offset, end, line.rstrip("\r\n")))
        offset = end
    if offset < len(text):
        ranges.append((offset, len(text), text[offset:]))
    return ranges


def parse_managed_block(text: str, *, source: str) -> ManagedBlock | None:
    starts: list[tuple[int, int]] = []
    ends: list[tuple[int, int]] = []
    active = False
    for start, end, line in _line_ranges(text):
        if line == START_MARKER:
            if active:
                raise HostSetupError(f"{source} has nested Keepygaga start markers")
            active = True
            starts.append((start, end))
        elif line == END_MARKER:
            if not active:
                raise HostSetupError(f"{source} has an unmatched Keepygaga end marker")
            active = False
            ends.append((start, end))
    if active:
        raise HostSetupError(f"{source} has an unmatched Keepygaga start marker")
    if len(starts) != len(ends):
        raise HostSetupError(f"{source} has corrupt Keepygaga markers")
    if len(starts) > 1:
        raise HostSetupError(f"{source} has duplicate Keepygaga managed blocks")
    if not starts:
        return None
    block_start = starts[0][0]
    block_end = ends[0][1]
    return ManagedBlock(block_start, block_end, text[block_start:block_end])


def load_canonical_contract(path: Path | None = None) -> str:
    contract_path = (path or _contract_path()).resolve()
    try:
        text = contract_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(
            f"Agent Contract could not be read: {contract_path}"
        ) from exc
    block = parse_managed_block(text, source=str(contract_path))
    if block is None or block.text != text:
        raise HostSetupError(
            "canonical Agent Contract must contain exactly one managed block"
        )
    version_line = f"{VERSION_PREFIX}{__version__} -->"
    lines = block.text.splitlines()
    if lines.count(version_line) != 1:
        raise HostSetupError(
            f"canonical Agent Contract must contain version {__version__} exactly once"
        )
    if any("HASH" in line.upper() or "SHA256" in line.upper() for line in lines[:3]):
        raise HostSetupError("canonical Agent Contract must use version-only ownership")
    if not text.endswith("\n"):
        text += "\n"
    return text


def load_legacy_contract(path: Path | None = None) -> str:
    legacy_path = (path or _legacy_contract_path()).resolve()
    try:
        legacy = legacy_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(
            f"legacy Agent Contract could not be read: {legacy_path}"
        ) from exc
    if START_MARKER in legacy or END_MARKER in legacy:
        raise HostSetupError("legacy Agent Contract must not contain managed markers")
    return legacy


def _legacy_ranges(existing: str, legacy: str) -> list[tuple[int, int]]:
    variants = {legacy, legacy.rstrip("\n"), legacy.replace("\n", "\r\n")}
    candidates: set[tuple[int, int]] = set()
    for variant in variants:
        if not variant:
            continue
        offset = 0
        while True:
            start = existing.find(variant, offset)
            if start < 0:
                break
            candidates.add((start, start + len(variant)))
            offset = start + len(variant)
    ranges: list[tuple[int, int]] = []
    for candidate in sorted(
        candidates, key=lambda item: (item[0], -(item[1] - item[0]))
    ):
        if any(
            candidate[0] >= accepted[0] and candidate[1] <= accepted[1]
            for accepted in ranges
        ):
            continue
        ranges.append(candidate)
    return sorted(ranges)


def merge_managed_contract(
    existing: str,
    canonical: str,
    *,
    source: str,
    legacy: str | None = None,
) -> str:
    current = parse_managed_block(existing, source=source)
    if current is not None:
        return existing[: current.start] + canonical + existing[current.end :]
    if legacy is not None:
        matches = _legacy_ranges(existing, legacy)
        if len(matches) > 1:
            raise HostSetupError(f"{source} has duplicate unmanaged legacy contracts")
        if matches:
            start, end = matches[0]
            return existing[:start] + canonical + existing[end:]
        if "# Keepygaga Agent Contract" in existing:
            raise HostSetupError(
                f"{source} has a modified unmanaged legacy contract; migrate it manually"
            )
    if not existing:
        return canonical
    separator = "" if existing.endswith(("\n", "\r")) else "\n"
    return f"{existing}{separator}\n{canonical}"


def _ensure_regular_target(path: Path) -> None:
    if path.is_symlink():
        raise HostSetupError(f"refusing symlink target: {path}")
    if path.exists() and not path.is_file():
        raise HostSetupError(f"target is not a regular file: {path}")


def _exclusive_backup(path: Path, original: bytes) -> Path:
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.keepygaga-backup-{index}")
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            if candidate.read_bytes() != original:
                raise HostSetupError(f"backup verification failed: {candidate}")
            return candidate
        except Exception:
            candidate.unlink(missing_ok=True)
            raise
    raise HostSetupError(f"could not allocate a backup path for {path}")


def _atomic_write(
    path: Path,
    content: bytes,
    *,
    expected_original: bytes | None | object = _EXPECTED_ANY,
) -> tuple[str, str | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_regular_target(path)
    original = path.read_bytes() if path.exists() else None
    if expected_original is not _EXPECTED_ANY and original != expected_original:
        raise HostSetupError(f"write conflict while updating {path}")
    if original == content:
        return "no_op", None

    backup = _exclusive_backup(path, original) if original is not None else None
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.keepygaga-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        _ensure_regular_target(path)
        live = path.read_bytes() if path.exists() else None
        if live != original:
            raise HostSetupError(f"write conflict while updating {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return "applied", str(backup) if backup else None


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(f"could not read UTF-8 file: {path}") from exc


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
    payload: Mapping[str, Any], python: Path, expected_env: Mapping[str, str]
) -> bool:
    transport = payload.get("transport")
    if not isinstance(transport, Mapping):
        return False
    return (
        payload.get("enabled") is True
        and transport.get("type") == "stdio"
        and transport.get("command") == str(python)
        and transport.get("args") == ["-m", "keepygaga.server"]
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
    return dict(environment)


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


def _probe_python(
    python: Path, *, statement: str, expected_stdout: str, label: str
) -> None:
    if not os.access(python, os.X_OK):
        raise HostSetupError(f"{label} is not executable: {python}")
    try:
        probe = subprocess.run(
            [str(python), "-I", "-c", statement],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"{label} probe could not run: {exc}") from exc
    if probe.returncode != 0 or probe.stdout != expected_stdout:
        detail = probe.stderr.strip() or probe.stdout.strip() or "unknown Python error"
        raise HostSetupError(f"{label} probe failed: {detail}")


def _probe_keepygaga_python(python: Path) -> None:
    token = "keepygaga-mcp-python-ok\n"
    _probe_python(
        python,
        statement=(
            f"import keepygaga.server; __import__('sys').stdout.write({token!r})"
        ),
        expected_stdout=token,
        label="Keepygaga Python",
    )


def _probe_hook_python(python: Path) -> None:
    token = "keepygaga-hook-python-ok\n"
    _probe_python(
        python,
        statement=f"__import__('sys').stdout.write({token!r})",
        expected_stdout=token,
        label="Hook Python",
    )


def _prepare_codex_mcp(
    codex_home: Path,
    config_path: Path,
    *,
    python: Path | None = None,
    codex_binary: Path | None = None,
) -> CodexMcpPlan:
    selected_python = Path(
        os.path.abspath((python or Path(sys.executable)).expanduser())
    )
    if not selected_python.is_file():
        raise HostSetupError(f"Keepygaga Python does not exist: {selected_python}")
    _probe_keepygaga_python(selected_python)
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
        if _matching_mcp_registration(current_payload, selected_python, desired_env):
            return CodexMcpPlan(
                codex_home=codex_home,
                codex_config=codex_config,
                config_original=config_original,
                selected_python=selected_python,
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
                current_payload, plan.selected_python, plan.desired_env
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
            "-m",
            "keepygaga.server",
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
            verified_payload, plan.selected_python, plan.desired_env
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


def _render_fragment(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for old, new in replacements.items():
            rendered = rendered.replace(old, new)
        return rendered
    if isinstance(value, list):
        return [_render_fragment(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _render_fragment(item, replacements) for key, item in value.items()
        }
    return value


def _load_hook_merger(
    runtime_root: Path,
) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    module_path = runtime_root / HOOK_MERGER_RELATIVE_PATH
    if not module_path.is_file() or module_path.is_symlink():
        raise HostSetupError(f"Agent Hook Runtime merger is missing: {module_path}")
    specification = importlib.util.spec_from_file_location(
        "_keepygaga_agent_hook_runtime_hook_config", module_path
    )
    if specification is None or specification.loader is None:
        raise HostSetupError(
            f"Agent Hook Runtime merger could not be loaded: {module_path}"
        )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    merger = getattr(module, "merge_hook_fragment", None)
    if not callable(merger):
        raise HostSetupError("Agent Hook Runtime does not expose merge_hook_fragment")
    return cast(Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]], merger)


def _default_hook_config_path() -> Path:
    configured = os.environ.get("AGENT_HOOK_RUNTIME_CONFIG", "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            raise HostSetupError("AGENT_HOOK_RUNTIME_CONFIG must be absolute")
        return Path(os.path.abspath(configured_path))
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if not appdata:
            raise HostSetupError(
                "APPDATA is required to locate Agent Hook Runtime config"
            )
        appdata_path = Path(appdata).expanduser()
        if not appdata_path.is_absolute():
            raise HostSetupError("APPDATA must be absolute")
        return Path(
            os.path.abspath(appdata_path / "agent-hook-runtime" / "config.json")
        )
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    if not base.is_absolute():
        raise HostSetupError("XDG_CONFIG_HOME must be absolute")
    return Path(os.path.abspath(base / "agent-hook-runtime" / "config.json"))


def _load_hook_runtime_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    _ensure_regular_target(path)
    try:
        loaded = json.loads(_read_utf8(path))
    except json.JSONDecodeError as exc:
        raise HostSetupError(
            f"Agent Hook Runtime config is invalid JSON: {path}"
        ) from exc
    if not isinstance(loaded, dict):
        raise HostSetupError(f"Agent Hook Runtime config must be an object: {path}")
    memory_root = loaded.get("memory_root")
    if (
        loaded.get("schema_version") != 1
        or not isinstance(memory_root, str)
        or not memory_root.strip()
    ):
        raise HostSetupError(
            f"existing file is not an Agent Hook Runtime config: {path}"
        )
    return loaded


def _reconcile_hook_runtime_config(path: Path, memory_root: Path) -> dict[str, object]:
    existing = _load_hook_runtime_config(path)
    merged = {**existing, "schema_version": 1, "memory_root": str(memory_root)}
    encoded = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    status, backup = _atomic_write(path, encoded)
    return _json_result(status, path=str(path), backup=backup)


def _validate_hook_command_path(path: Path, *, label: str) -> None:
    value = str(path)
    unsafe = {"\x00", "\r", "\n", '"', "$", "`"}
    if os.name == "nt":
        unsafe.update({"%", "!", "^", "&", "|", "<", ">"})
    else:
        unsafe.add("\\")
    if any(character in value for character in unsafe):
        raise HostSetupError(f"{label} contains unsafe shell characters: {path}")


def _prepare_codex_hooks(
    codex_home: Path,
    memory_root: Path,
    runtime_root: Path,
    hook_python: Path,
    *,
    hook_config_path: Path | None = None,
) -> CodexHookPlan:
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
    if selected_hook_config.is_symlink():
        raise HostSetupError(
            f"Agent Hook Runtime config must not be a symlink: {selected_hook_config}"
        )
    _load_hook_runtime_config(selected_hook_config)
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
    smoke_environment["AGENT_HOOK_RUNTIME_CONFIG"] = str(plan.hook_config_path)
    try:
        smoke = subprocess.run(
            [
                str(plan.selected_python),
                str(plan.selected_runtime / "hooks/context_hook.py"),
                "codex",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=smoke_environment,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"Codex context Hook smoke could not run: {exc}") from exc
    try:
        smoke_payload = json.loads(smoke.stdout)
    except json.JSONDecodeError as exc:
        raise HostSetupError("Codex context Hook smoke returned invalid JSON") from exc
    if smoke.returncode != 0 or not isinstance(smoke_payload, dict):
        raise HostSetupError("Codex context Hook smoke failed")


def _apply_codex_hooks_plan(plan: CodexHookPlan) -> dict[str, object]:
    live_hooks = plan.hooks_path.read_bytes() if plan.hooks_path.exists() else None
    if live_hooks != plan.hooks_original:
        raise HostSetupError(f"write conflict while updating {plan.hooks_path}")
    hook_config = _reconcile_hook_runtime_config(
        plan.hook_config_path, plan.memory_root
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
    if not config.memory.root.strip():
        raise HostSetupError("memory.root is not configured")
    if (hook_runtime is None) != (hook_python is None):
        raise HostSetupError("hook runtime and hook Python must be supplied together")
    memory_root = Path(config.memory.root).expanduser().resolve()
    doctor = run_doctor(config_path.resolve(), project_root=PROJECT_ROOT)
    checks = doctor.get("checks")
    if not isinstance(checks, list):
        raise HostSetupError("Doctor did not return a checks list")
    memory_check = next(
        (
            check
            for check in checks
            if isinstance(check, Mapping) and check.get("id") == "memory_tree"
        ),
        None,
    )
    details = memory_check.get("details") if isinstance(memory_check, Mapping) else None
    memory_status = (
        memory_check.get("status") if isinstance(memory_check, Mapping) else None
    )
    valid_soft_limit_warning = (
        memory_status == "warning"
        and isinstance(details, Mapping)
        and details.get("split_recommended") is True
    )
    if memory_status != "ok" and not valid_soft_limit_warning:
        source_status = (
            details.get("source_status") if isinstance(details, Mapping) else None
        )
        suffix = f" ({source_status})" if isinstance(source_status, str) else ""
        raise HostSetupError(f"memory tree did not pass Doctor{suffix}")
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
    try:
        selected_home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HostSetupError(f"Codex home could not be created: {exc}") from exc

    lock = FileLock(str(selected_home / ".keepygaga-host-setup.lock"), timeout=30)
    components: dict[str, object] = {}
    try:
        lock.acquire()
    except (FileLockTimeout, OSError) as exc:
        raise HostSetupError(f"Codex setup lock could not be acquired: {exc}") from exc
    try:
        try:
            hook_plan = (
                _prepare_codex_hooks(
                    selected_home,
                    memory_root,
                    hook_runtime,
                    hook_python,
                    hook_config_path=hook_config_path,
                )
                if hook_runtime is not None and hook_python is not None
                else None
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
            if hook_runtime is None and hook_python is None:
                hooks = _json_result(
                    "skipped", reason="compatible Agent Hook Runtime was not selected"
                )
            else:
                if hook_plan is None:
                    raise HostSetupError("Codex Hook plan was not prepared")
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
