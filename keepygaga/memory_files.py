from __future__ import annotations

import errno
import os
from contextlib import suppress
from pathlib import Path

from filelock import FileLock

from keepygaga.memory_contract import NEW_DIRECTORY_MODE, NEW_FILE_MODE


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _absolute_without_resolving_links(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _exclusive_create(target: Path, text: str) -> bool:
    if not target.parent.exists():
        _mkdir_private(target.parent, parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        descriptor = os.open(
            target, flags, NEW_FILE_MODE if _posix_mode_supported() else 0o666
        )
    except FileExistsError:
        return False
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False
        raise
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            target.unlink()
        raise
    return True


def _posix_mode_supported() -> bool:
    return os.name != "nt"


def _memory_lock(lock_path: Path) -> FileLock:
    _ensure_private_lock_file(lock_path)
    return FileLock(str(lock_path), timeout=30)


def _ensure_private_lock_file(lock_path: Path) -> None:
    if not _posix_mode_supported() or not lock_path.parent.is_dir():
        return
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        descriptor = os.open(lock_path, flags, NEW_FILE_MODE)
    except FileExistsError:
        return
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ENOENT, errno.ENOTDIR}:
            return
        raise
    os.close(descriptor)


def _mkdir_private(target: Path, *, parents: bool = False) -> None:
    if parents:
        missing: list[Path] = []
        current = target
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for directory in reversed(missing):
            _mkdir_new(directory)
        return
    _mkdir_new(target)


def _mkdir_new(target: Path) -> None:
    if _posix_mode_supported():
        target.mkdir(mode=NEW_DIRECTORY_MODE)
        return
    target.mkdir()


def _chmod_private_file(target: Path) -> None:
    if _posix_mode_supported():
        os.chmod(target, NEW_FILE_MODE)


def _permission_too_open(mode: int, *, directory: bool) -> bool:
    if not _posix_mode_supported():
        return False
    allowed = NEW_DIRECTORY_MODE if directory else NEW_FILE_MODE
    return (mode & 0o777) & ~allowed != 0
