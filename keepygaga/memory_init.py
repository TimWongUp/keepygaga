from __future__ import annotations

from pathlib import Path, PurePosixPath

from filelock import Timeout

from keepygaga.codec import MemoryDocument, render_memory_file
from keepygaga.config import MemoryFilesConfig
from keepygaga.errors import MemoryValidationError
from keepygaga.memory_contract import DEFAULT_DESCRIPTIONS
from keepygaga.memory_files import (
    _absolute_without_resolving_links,
    _exclusive_create,
    _is_link_like,
    _memory_lock,
    _mkdir_private,
)
from keepygaga.memory_store import MemoryStore
from keepygaga.paths import DYNAMIC_DIRS, FIXED_PATHS


def _default_document(path: str) -> MemoryDocument:
    return MemoryDocument(
        name=PurePosixPath(path).stem,
        description=DEFAULT_DESCRIPTIONS[path],
        aliases=(),
        facts=(),
    )


def _prepare_memory_root(
    root: Path,
    config: MemoryFilesConfig,
    created_directories: list[Path],
) -> None:
    if _is_link_like(root):
        raise MemoryValidationError(
            "invalid_source", f"memory root must not be a symlink or junction: {root}"
        )
    if root.exists() and not root.is_dir():
        raise MemoryValidationError(
            "invalid_source", f"memory root must be a directory: {root}"
        )
    if root.is_dir():
        MemoryStore(root, config)._load_catalog(require_complete=False)
    if root.exists():
        root.mkdir(parents=True, exist_ok=True)
        return
    _mkdir_private(root, parents=True)
    created_directories.append(root)


def _prepare_dynamic_directories(
    root: Path, created_directories: list[Path]
) -> None:
    for directory in DYNAMIC_DIRS:
        target = root / directory
        if _is_link_like(target) or (target.exists() and not target.is_dir()):
            raise MemoryValidationError(
                "invalid_source", f"memory path must be a directory: {target}"
            )
        if target.exists():
            target.mkdir(exist_ok=True)
        else:
            _mkdir_private(target)
            created_directories.append(target)


def _prepare_fixed_pages(root: Path, rendered: list[Path]) -> None:
    for relative in FIXED_PATHS:
        target = root / relative
        if _is_link_like(target):
            raise MemoryValidationError(
                "invalid_source", f"memory page must not be a symlink: {target}"
            )
        if target.exists():
            if not target.is_file():
                raise MemoryValidationError(
                    "invalid_source", f"memory page must be a regular file: {target}"
                )
            continue
        if _exclusive_create(
            target, render_memory_file(_default_document(relative), relative)
        ):
            rendered.append(target)


def initialize_memory_tree(
    root: Path,
    _config: MemoryFilesConfig,
) -> dict[str, object]:
    rendered: list[Path] = []
    created_directories: list[Path] = []
    try:
        root = _absolute_without_resolving_links(root)
        _prepare_memory_root(root, _config, created_directories)
        lock_path = root / ".keepygaga.lock"
        if _is_link_like(lock_path):
            raise MemoryValidationError(
                "invalid_source", f"memory lock path must not be a symlink: {lock_path}"
            )
        with _memory_lock(lock_path):
            store = MemoryStore(root, _config)
            store._load_catalog(require_complete=False)
            _prepare_dynamic_directories(root, created_directories)
            _prepare_fixed_pages(root, rendered)
            store._load_catalog()
    except Timeout:
        payload: dict[str, object] = {
            "status": "partial_commit" if created_directories else "write_conflict",
            "message": "could not acquire the global memory lock",
        }
        if created_directories:
            payload["directories"] = [str(path) for path in created_directories]
        return payload
    except MemoryValidationError as exc:
        payload = exc.response()
        if rendered:
            payload["files"] = [str(path) for path in rendered]
        if created_directories:
            payload["directories"] = [str(path) for path in created_directories]
        return payload
    except PermissionError as exc:
        return {
            "status": (
                "partial_commit"
                if rendered or created_directories
                else "permission_denied"
            ),
            "message": f"{type(exc).__name__}: {exc}",
            "files": [str(path) for path in rendered],
            "directories": [str(path) for path in created_directories],
        }
    except OSError as exc:
        return {
            "status": (
                "partial_commit" if rendered or created_directories else "write_failed"
            ),
            "message": f"{type(exc).__name__}: {exc}",
            "files": [str(path) for path in rendered],
            "directories": [str(path) for path in created_directories],
        }
    payload: dict[str, object] = {
        "status": "applied" if rendered or created_directories else "no_op",
        "files": [str(path) for path in rendered],
        "directories": [str(path) for path in created_directories],
    }
    if rendered:
        payload["onboarding"] = {
            "optional": True,
            "created_pages": [path.relative_to(root).as_posix() for path in rendered],
        }
    return payload
