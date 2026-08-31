from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from keepygaga.config import PROJECT_ROOT, KeepygagaConfig
from keepygaga.diagnostics import run_doctor
from keepygaga.version import CONTRACT_VERSION

START_MARKER = "<!-- KEEPYGAGA:START -->"
END_MARKER = "<!-- KEEPYGAGA:END -->"
VERSION_PREFIX = "<!-- KEEPYGAGA:CONTRACT:"
CONTRACT_RELATIVE_PATH = Path("docs/agent-contract.md")
LEGACY_CONTRACT_RELATIVE_PATH = Path("docs/legacy-agent-contract-v0.md")
HOOK_MERGER_RELATIVE_PATH = Path("agent_hook_runtime/hook_config.py")
HOOK_ENTRYPOINTS = (
    "hooks/context_hook.py",
    "hooks/memory_route_hook.py",
    "hooks/closeout_hook.py",
)
EXPECTED_ANY = object()


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


def json_result(status: str, **values: object) -> dict[str, object]:
    return {"status": status, **values}


def validate_host_source(
    config_path: Path, config: KeepygagaConfig
) -> tuple[Path, dict[str, object]]:
    if not config.memory.root.strip():
        raise HostSetupError("memory.root is not configured")
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
    permission_warnings = (
        details.get("permission_warnings") if isinstance(details, Mapping) else None
    )
    has_permission_warning = bool(
        isinstance(permission_warnings, list) and permission_warnings
    )
    soft_warning = (
        memory_status == "warning"
        and isinstance(details, Mapping)
        and not has_permission_warning
        and (
            details.get("split_recommended") is True
            or details.get("dynamic_page_limit_exceeded") is True
        )
    )
    invalid_checks = [
        str(check.get("id", "unknown"))
        for check in checks
        if isinstance(check, Mapping)
        and check.get("status") != "ok"
        and check is not memory_check
    ]
    if memory_status != "ok" and not soft_warning:
        source_status = (
            details.get("source_status") if isinstance(details, Mapping) else None
        )
        suffix = f" ({source_status})" if isinstance(source_status, str) else ""
        raise HostSetupError(f"memory tree did not pass Doctor{suffix}")
    if invalid_checks:
        raise HostSetupError(
            f"Doctor reported non-ok checks: {', '.join(invalid_checks)}"
        )
    return Path(config.memory.root).expanduser().resolve(), doctor


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
    version_line = f"{VERSION_PREFIX}{CONTRACT_VERSION} -->"
    lines = block.text.splitlines()
    if lines.count(version_line) != 1:
        raise HostSetupError(
            "canonical Agent Contract must contain contract version "
            f"{CONTRACT_VERSION} exactly once"
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


def remove_managed_contract(
    existing: str,
    *,
    source: str,
    legacy: str | None = None,
) -> str:
    current = parse_managed_block(existing, source=source)
    if current is not None:
        removed = existing[: current.start] + existing[current.end :]
        if legacy is not None:
            leftover = _legacy_ranges(removed, legacy)
            if leftover:
                raise HostSetupError(
                    f"{source} still contains an unmanaged legacy contract"
                )
            if "# Keepygaga Agent Contract" in removed:
                raise HostSetupError(
                    f"{source} has a modified unmanaged legacy contract; migrate it manually"
                )
        return removed
    if legacy is not None:
        matches = _legacy_ranges(existing, legacy)
        if len(matches) > 1:
            raise HostSetupError(f"{source} has duplicate unmanaged legacy contracts")
        if matches:
            start, end = matches[0]
            return existing[:start] + existing[end:]
        if "# Keepygaga Agent Contract" in existing:
            raise HostSetupError(
                f"{source} has a modified unmanaged legacy contract; migrate it manually"
            )
    return existing


def ensure_regular_target(path: Path) -> None:
    try:
        if path.is_symlink():
            raise HostSetupError(f"refusing symlink target: {path}")
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            raise HostSetupError(f"refusing junction target: {path}")
        if path.exists() and not path.is_file():
            raise HostSetupError(f"target is not a regular file: {path}")
    except OSError as exc:
        raise HostSetupError(f"target could not be inspected: {path}") from exc


def ensure_safe_parent(path: Path) -> None:
    current = path.parent
    while current != current.parent:
        try:
            if current.is_symlink():
                raise HostSetupError(f"refusing symlink parent: {current}")
            is_junction = getattr(current, "is_junction", None)
            if callable(is_junction) and is_junction():
                raise HostSetupError(f"refusing junction parent: {current}")
        except OSError as exc:
            raise HostSetupError(f"parent could not be inspected: {current}") from exc
        current = current.parent


def exclusive_backup(path: Path, original: bytes) -> Path:
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


def atomic_write(
    path: Path,
    content: bytes,
    *,
    expected_original: bytes | None | object = EXPECTED_ANY,
) -> tuple[str, str | None]:
    ensure_safe_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_safe_parent(path)
    ensure_regular_target(path)
    original = path.read_bytes() if path.exists() else None
    if expected_original is not EXPECTED_ANY and original != expected_original:
        raise HostSetupError(f"write conflict while updating {path}")
    if original == content:
        return "no_op", None

    backup = exclusive_backup(path, original) if original is not None else None
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
        ensure_regular_target(path)
        live = path.read_bytes() if path.exists() else None
        if live != original:
            raise HostSetupError(f"write conflict while updating {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return "applied", str(backup) if backup else None


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeError) as exc:
        raise HostSetupError(f"could not read UTF-8 file: {path}") from exc


def run_captured(
    command: Sequence[str] | str,
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
    input: str | None = None,
    executable: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=None if env is None else dict(env),
        cwd=cwd,
        input=input,
        executable=executable,
    )


def captured_output(
    completed: subprocess.CompletedProcess[str],
    *,
    limit: int | None = None,
) -> str:
    text = (completed.stderr or "").strip() or (completed.stdout or "").strip()
    return text if limit is None else text[:limit]


def captured_streams(completed: subprocess.CompletedProcess[str]) -> str:
    return f"{completed.stderr or ''}\n{completed.stdout or ''}"


def _probe_python(
    python: Path, *, statement: str, expected_stdout: str, label: str
) -> None:
    if not os.access(python, os.X_OK):
        raise HostSetupError(f"{label} is not executable: {python}")
    try:
        probe = run_captured(
            [str(python), "-I", "-c", statement],
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostSetupError(f"{label} probe could not run: {exc}") from exc
    if probe.returncode != 0 or probe.stdout != expected_stdout:
        detail = captured_output(probe) or "unknown Python error"
        raise HostSetupError(f"{label} probe failed: {detail}")


def probe_keepygaga_python(python: Path) -> None:
    token = "keepygaga-mcp-python-ok\n"
    _probe_python(
        python,
        statement=(
            f"import keepygaga.server; __import__('sys').stdout.write({token!r})"
        ),
        expected_stdout=token,
        label="Keepygaga Python",
    )


def probe_hook_python(python: Path) -> None:
    token = "keepygaga-hook-python-ok\n"
    _probe_python(
        python,
        statement=f"__import__('sys').stdout.write({token!r})",
        expected_stdout=token,
        label="Hook Python",
    )


def render_fragment(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for old, new in replacements.items():
            rendered = rendered.replace(old, new)
        return rendered
    if isinstance(value, list):
        return [render_fragment(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: render_fragment(item, replacements) for key, item in value.items()}
    return value


def load_hook_merger(
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


def default_hook_config_path() -> Path:
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


def _parse_hook_runtime_config(original: bytes | None, *, path: Path) -> dict[str, Any]:
    if original is None:
        return {}
    try:
        loaded = json.loads(original.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
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


def load_hook_runtime_config(path: Path) -> dict[str, Any]:
    ensure_regular_target(path)
    try:
        original = path.read_bytes() if path.exists() else None
    except OSError as exc:
        raise HostSetupError(
            f"Agent Hook Runtime config could not be read: {path}"
        ) from exc
    return _parse_hook_runtime_config(original, path=path)


def prepare_hook_runtime_config(
    path: Path, memory_root: Path
) -> tuple[bytes | None, bytes]:
    ensure_regular_target(path)
    try:
        original = path.read_bytes() if path.exists() else None
    except OSError as exc:
        raise HostSetupError(
            f"Agent Hook Runtime config could not be read: {path}"
        ) from exc
    existing = _parse_hook_runtime_config(original, path=path)
    merged = {**existing, "schema_version": 1, "memory_root": str(memory_root)}
    if merged == existing and original is not None:
        return original, original
    content = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return original, content


def validate_hook_command_path(path: Path, *, label: str) -> None:
    value = str(path)
    unsafe = {"\x00", "\r", "\n", '"', "$", "`"}
    if os.name == "nt":
        unsafe.update({"%", "!", "^", "&", "|", "<", ">"})
    else:
        unsafe.add("\\")
    if any(character in value for character in unsafe):
        raise HostSetupError(f"{label} contains unsafe shell characters: {path}")
