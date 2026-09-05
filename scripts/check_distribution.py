#!/usr/bin/env python3
"""Fail when built artifacts omit product assets or include split-repo code."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

from keepygaga.version import CONTRACT_VERSION


def names(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    with tarfile.open(path) as archive:
        return set(archive.getnames())


def member_text(path: Path, suffix: str) -> str:
    normalized_suffix = suffix.lower()
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            matches = [
                name
                for name in archive.namelist()
                if name.replace("\\", "/").lower().endswith(normalized_suffix)
            ]
            if len(matches) != 1:
                raise SystemExit(f"expected one {suffix} in {path}")
            return archive.read(matches[0]).decode("utf-8")
    with tarfile.open(path) as archive:
        matches = [
            member
            for member in archive.getmembers()
            if member.name.replace("\\", "/").lower().endswith(normalized_suffix)
        ]
        if len(matches) != 1:
            raise SystemExit(f"expected one {suffix} in {path}")
        extracted = archive.extractfile(matches[0])
        if extracted is None:
            raise SystemExit(f"could not read {suffix} from {path}")
        return extracted.read().decode("utf-8")


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
        contract = (
            "share/keepygaga/agent-contract.md"
            if artifact.suffix == ".whl"
            else "docs/agent-contract.md"
        )
        required = (
            "keepygaga/mcp_instructions.md",
            "keepygaga/hooks/context.py",
            contract,
        )
        if any(
            not any(name.endswith(item) for name in normalized) for item in required
        ):
            raise SystemExit(f"standalone runtime assets missing from {artifact}")
        content_requirements = {
            "keepygaga/mcp_instructions.md": (
                "trusted first-stage semantic routes",
                "untrusted data, never instructions",
            ),
            "keepygaga/hooks/context.py": ("不可信路由标签",),
            contract: (
                f"KEEPYGAGA:CONTRACT:{CONTRACT_VERSION}",
                "trusted first-stage semantic routes",
                "credential-free canonical remote URLs",
            ),
        }
        for suffix, markers in content_requirements.items():
            content = member_text(artifact, suffix)
            if any(marker not in content for marker in markers):
                raise SystemExit(f"stale runtime asset {suffix} in {artifact}")
    print("distribution inventory ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
