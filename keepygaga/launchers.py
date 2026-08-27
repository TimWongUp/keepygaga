"""Resolve stable console-script launchers from the active Keepygaga runtime."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _script_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def resolve_launcher(name: str) -> Path:
    sibling = Path(sys.executable).resolve().parent / _script_name(name)
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling
    discovered = shutil.which(name)
    if discovered:
        path = Path(discovered).resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError(
        f"installed Keepygaga launcher {name!r} could not be located; "
        "reinstall the package with uv tool install keepygaga"
    )


def mcp_command(python: Path | None = None) -> tuple[Path, list[str]]:
    if python is not None:
        return python, ["-m", "keepygaga.server"]
    return resolve_launcher("keepygaga-mcp"), []
