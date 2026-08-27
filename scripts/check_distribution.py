#!/usr/bin/env python3
"""Fail when built artifacts omit product assets or include split-repo code."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


def names(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    with tarfile.open(path) as archive:
        return set(archive.getnames())


def main() -> int:
    artifacts = [Path(value) for value in sys.argv[1:]]
    if not artifacts:
        raise SystemExit("pass wheel and sdist paths")
    for artifact in artifacts:
        members = names(artifact)
        normalized = {name.replace("\\", "/").lower() for name in members}
        forbidden = ("keepygaga_knowledge", "/knowledge/", "/dashboard/")
        if any(marker in name for name in normalized for marker in forbidden):
            raise SystemExit(f"split-repo code leaked into {artifact}")
        required = ("keepygaga/mcp_instructions.md", "keepygaga/hooks/context.py")
        if any(not any(name.endswith(item) for name in normalized) for item in required):
            raise SystemExit(f"standalone runtime assets missing from {artifact}")
    print("distribution inventory ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
