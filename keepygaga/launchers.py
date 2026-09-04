"""Resolve stable console-script launchers from the active Keepygaga runtime."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _script_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def resolve_active_launcher(name: str) -> Path:
    script_name = _script_name(name)
    script_directory = "Scripts" if os.name == "nt" else "bin"
    candidates = (
        Path(sys.prefix) / script_directory / script_name,
        Path(sys.executable).parent / script_name,
    )
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise RuntimeError(
        f"active Keepygaga launcher {name!r} could not be located in {sys.prefix}"
    )


def resolve_launcher(name: str) -> Path:
    try:
        return resolve_active_launcher(name)
    except RuntimeError:
        pass
    discovered = shutil.which(name)
    if discovered:
        path = Path(discovered).resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError(
        f"installed Keepygaga launcher {name!r} could not be located; "
        "reinstall the GitHub Release wheel with uv tool install --force PATH_TO_WHEEL"
    )


def mcp_command(python: Path | None = None) -> tuple[Path, list[str]]:
    if python is not None:
        return python, ["-m", "keepygaga.server"]
    return resolve_launcher("keepygaga-mcp"), []
