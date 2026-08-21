from __future__ import annotations

from pathlib import PurePosixPath

from keepygaga.errors import MemoryValidationError

FIXED_PATHS = ("profile.md", "preferences.md")
DYNAMIC_DIRS = ("topics", "areas", "people")
DYNAMIC_STEM_RE = None  # Will be set by memory.py to avoid circular import


def canonical_memory_path(value: str) -> str:
    from keepygaga.memory import DYNAMIC_DIRS, DYNAMIC_STEM_RE, FIXED_PATHS

    if not isinstance(value, str):
        raise MemoryValidationError("invalid_path", "path must be a string")
    if not value or value.strip() != value or "\\" in value or "\x00" in value:
        raise MemoryValidationError(
            "invalid_path", "path must be a canonical POSIX-relative key"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or ".." in path.parts:
        raise MemoryValidationError(
            "invalid_path", "path must be a canonical POSIX-relative key"
        )
    if value in FIXED_PATHS:
        return value
    if (
        len(path.parts) == 2
        and path.parts[0] in DYNAMIC_DIRS
        and path.suffix == ".md"
        and DYNAMIC_STEM_RE.fullmatch(path.stem)
        and not path.name.startswith(".")
    ):
        return value
    raise MemoryValidationError(
        "invalid_path",
        "path must be a fixed memory file or one direct topics/areas/people "
        "Markdown child with a lowercase kebab-case stem",
        path=value,
    )


def canonical_path(value: str) -> str:
    return canonical_memory_path(value)


def is_dynamic_path(path: str) -> bool:
    canonical = canonical_memory_path(path)
    return PurePosixPath(canonical).parts[0] in DYNAMIC_DIRS
