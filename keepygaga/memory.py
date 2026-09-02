from __future__ import annotations

import errno
import os
import re
import stat
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from filelock import FileLock, Timeout
from pydantic import ConfigDict, Field, field_validator, model_validator

from keepygaga.codec import (
    FACT_LINE_RE as FACT_LINE_RE,
)
from keepygaga.codec import (
    FRONTMATTER_KEY_RE as FRONTMATTER_KEY_RE,
)
from keepygaga.codec import (
    MAX_FACT_CONTENT_CHARS as MAX_FACT_CONTENT_CHARS,
)
from keepygaga.codec import (
    Basis as Basis,
)
from keepygaga.codec import (
    Fact as Fact,
)
from keepygaga.codec import (
    FactSelector as FactSelector,
)
from keepygaga.codec import (
    MemoryDocument as MemoryDocument,
)
from keepygaga.codec import (
    StoredFact as StoredFact,
)
from keepygaga.codec import (
    StrictModel as StrictModel,
)
from keepygaga.codec import (
    _identity,
    _one_line,
    fact_key,
    normalize_text,
    parse_memory_file,
    parse_page_metadata,
    receipt,
    render_memory_file,
    repair_memory_file,
    sha256_text,
    stored_fact,
    unicode_chars,
    validate_document,
)
from keepygaga.config import MemoryFilesConfig
from keepygaga.errors import MemoryValidationError
from keepygaga.paths import (
    DYNAMIC_DIRS as DYNAMIC_DIRS,
)
from keepygaga.paths import (
    DYNAMIC_STEM_RE as DYNAMIC_STEM_RE,
)
from keepygaga.paths import (
    FIXED_PATHS as FIXED_PATHS,
)
from keepygaga.paths import (
    canonical_memory_path as canonical_memory_path,
)
from keepygaga.paths import (
    canonical_path as canonical_path,
)
from keepygaga.paths import (
    is_dynamic_path,
)

PROFILE_PAGE_LIMIT = 2000
PREFERENCES_PAGE_LIMIT = 2000
DYNAMIC_PAGE_LIMIT = 5000
MAX_REPAIR_INPUT_CHARS = DYNAMIC_PAGE_LIMIT * 2
MAX_DESCRIPTION_CHARS = 80
MAX_ALIASES_PER_PAGE = 6
MAX_READ_PATHS = 15
MAX_MUTATION_OPERATIONS = 15
MAX_FACTS_PER_OPERATION = 30
DYNAMIC_PAGE_LIMITS = {"topics": 50, "areas": 50, "people": 100}
NEW_DIRECTORY_MODE = 0o700
NEW_FILE_MODE = 0o600

VERSION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_DESCRIPTIONS = {
    "profile.md": "用户明确陈述的稳定身份、背景与长期角色。",
    "preferences.md": "用户希望 Agent 长期遵循的回应方式、工作偏好与条件检索偏好。",
}


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()

__all__ = [
    "AddOperation",
    "AddOperations",
    "Basis",
    "CreateOperation",
    "CreateOperations",
    "DEFAULT_DESCRIPTIONS",
    "DYNAMIC_DIRS",
    "DYNAMIC_STEM_RE",
    "DeleteFactOperation",
    "DeleteOperation",
    "DeleteOperations",
    "DeletePageOperation",
    "FACT_LINE_RE",
    "FIXED_PATHS",
    "FRONTMATTER_KEY_RE",
    "Fact",
    "FactSelector",
    "StoredFact",
    "LoadedFile",
    "DYNAMIC_PAGE_LIMIT",
    "DYNAMIC_PAGE_LIMITS",
    "MAX_FACTS_PER_OPERATION",
    "MAX_FACT_CONTENT_CHARS",
    "MAX_MUTATION_OPERATIONS",
    "MAX_READ_PATHS",
    "NEW_DIRECTORY_MODE",
    "NEW_FILE_MODE",
    "MemoryDocument",
    "MemoryScope",
    "MemoryStore",
    "MoveOperation",
    "MoveOperations",
    "PREFERENCES_PAGE_LIMIT",
    "PROFILE_PAGE_LIMIT",
    "ReadPaths",
    "RepairPageOperation",
    "RenameOperation",
    "RenameOperations",
    "StrictModel",
    "UpdateFactOperation",
    "UpdateOperation",
    "UpdateOperations",
    "UpdatePageOperation",
    "VERSION_RE",
    "canonical_memory_path",
    "canonical_path",
    "initialize_memory_tree",
    "is_dynamic_path",
    "parse_memory_file",
    "render_memory_file",
    "page_limit",
]


MemoryScope = Literal["topics", "areas", "people"]
ExistingPagePath = Annotated[
    str,
    Field(description="Canonical existing page path from the current Route Catalog."),
]
DynamicPagePath = Annotated[
    str,
    Field(
        description=(
            "New direct topics/, areas/, or people/ Markdown path using a canonical slug."
        )
    ),
]
CurrentPageVersion = Annotated[
    str,
    Field(
        description=(
            "Opaque version from the latest Page Snapshot of this page; pass unchanged."
        )
    ),
]


def _agent_description(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("description must be a string")
    normalized = _one_line(value, "description")
    if unicode_chars(normalized) > MAX_DESCRIPTION_CHARS:
        raise ValueError(
            f"description cannot exceed {MAX_DESCRIPTION_CHARS} characters"
        )
    return normalized


class CreateOperation(StrictModel):
    path: DynamicPagePath
    description: str = Field(max_length=MAX_DESCRIPTION_CHARS)
    aliases: list[str] = Field(max_length=MAX_ALIASES_PER_PAGE)
    facts: list[Fact] = Field(max_length=MAX_FACTS_PER_OPERATION)

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str:
        return _agent_description(value)


class AddOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    facts: list[Fact] = Field(
        min_length=1,
        max_length=MAX_FACTS_PER_OPERATION,
        description="Facts to append; Store validation rejects exact duplicates only.",
    )


class UpdateFactOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    target: Literal["fact"] = Field(
        description="Select exact Fact replacement rather than page metadata update."
    )
    old_fact: FactSelector
    new_fact: Fact = Field(
        description="Replacement Fact; a stated basis cannot be downgraded to observed."
    )

    @model_validator(mode="after")
    def validate_change(self) -> UpdateFactOperation:
        if fact_key(self.old_fact) == fact_key(self.new_fact):
            raise ValueError("old_fact and new_fact must differ")
        return self


class UpdatePageOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    target: Literal["page"] = Field(
        description="Select page description or aliases update rather than Fact replacement."
    )
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    aliases: list[str] | None = Field(default=None, max_length=MAX_ALIASES_PER_PAGE)

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        if value is None:
            return None
        return _agent_description(value)

    @model_validator(mode="after")
    def validate_change(self) -> UpdatePageOperation:
        if self.description is None and self.aliases is None:
            raise ValueError("page update requires description or aliases")
        return self


class RepairPageOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    target: Literal["repair"] = Field(
        description="Mechanically canonicalize one repairable page without semantic edits."
    )


class MoveOperation(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["destination_path", "destination_version"],
                    "properties": {
                        "destination_path": {"type": "string"},
                        "destination_version": {"type": "string"},
                        "new_path": {"type": "null"},
                        "description": {"type": "null"},
                        "aliases": {"type": "null"},
                    },
                },
                {
                    "required": ["new_path", "description", "aliases"],
                    "properties": {
                        "destination_path": {"type": "null"},
                        "destination_version": {"type": "null"},
                        "new_path": {"type": "string"},
                        "description": {"type": "string"},
                        "aliases": {"type": "array"},
                    },
                },
            ]
        }
    )

    source_path: ExistingPagePath
    source_version: CurrentPageVersion
    destination_path: ExistingPagePath | None = None
    destination_version: CurrentPageVersion | None = None
    new_path: DynamicPagePath | None = None
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    aliases: list[str] | None = Field(default=None, max_length=MAX_ALIASES_PER_PAGE)
    facts: list[FactSelector] = Field(
        min_length=1,
        max_length=MAX_FACTS_PER_OPERATION,
        description=(
            "All exact Facts to move between this source/destination pair in one "
            "operation; copy them unchanged from the latest source Page Snapshot."
        ),
    )

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        return _agent_description(value) if value is not None else None

    @model_validator(mode="after")
    def validate_destination(self) -> MoveOperation:
        existing = (
            self.destination_path is not None or self.destination_version is not None
        )
        new = (
            self.new_path is not None
            or self.description is not None
            or self.aliases is not None
        )
        if existing == new:
            raise ValueError(
                "move requires exactly one existing or new destination mode"
            )
        if existing and (
            self.destination_path is None or self.destination_version is None
        ):
            raise ValueError("existing destination requires path and version")
        if new and (
            self.new_path is None or self.description is None or self.aliases is None
        ):
            raise ValueError(
                "new destination requires new_path, description, and aliases"
            )
        return self


class RenameOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    new_path: DynamicPagePath


class DeleteFactOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    target: Literal["fact"] = Field(description="Delete one exact Fact.")
    fact: FactSelector
    authorization: Literal["user_requested"] = Field(
        description=(
            "Audit assertion; set only after explicit current-turn user authorization."
        )
    )


class DeletePageOperation(StrictModel):
    path: ExistingPagePath
    if_version: CurrentPageVersion
    target: Literal["page"] = Field(description="Delete one dynamic page.")
    authorization: Literal["user_requested"] = Field(
        description=(
            "Audit assertion; set only after explicit current-turn user authorization."
        )
    )


DeleteOperation = Annotated[
    DeleteFactOperation | DeletePageOperation,
    Field(discriminator="target"),
]
UpdateOperation = Annotated[
    UpdateFactOperation | UpdatePageOperation | RepairPageOperation,
    Field(discriminator="target"),
]

CreateOperations = Annotated[
    list[CreateOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description="Page creations validated as one batch; repeated paths are rejected.",
    ),
]
AddOperations = Annotated[
    list[AddOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description="Fact additions validated as one batch; each path must be unique.",
    ),
]
UpdateOperations = Annotated[
    list[UpdateOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description="Exact updates validated as one batch; each path must be unique.",
    ),
]
MoveOperations = Annotated[
    list[MoveOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description=(
            "Exact Fact moves validated as one batch. Use one operation per disjoint "
            "source/destination pair and include all Facts for that pair in facts; "
            "every page path may appear only once across the batch."
        ),
    ),
]
RenameOperations = Annotated[
    list[RenameOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description="Dynamic page renames; every old and new path must be unique.",
    ),
]
DeleteOperations = Annotated[
    list[DeleteOperation],
    Field(
        min_length=1,
        max_length=MAX_MUTATION_OPERATIONS,
        description="Authorized exact deletions; each path must be unique.",
    ),
]
ReadPaths = Annotated[
    list[ExistingPagePath],
    Field(
        min_length=1,
        max_length=MAX_READ_PATHS,
        description="Unique canonical page paths from the current Route Catalog.",
    ),
]


@dataclass(frozen=True)
class LoadedFile:
    path: str
    document: MemoryDocument
    text: str
    version: str


def page_limit(path: str) -> int:
    if path == "profile.md":
        return PROFILE_PAGE_LIMIT
    if path == "preferences.md":
        return PREFERENCES_PAGE_LIMIT
    return DYNAMIC_PAGE_LIMIT


def _local_date() -> str:
    return calendar_date.today().isoformat()


def _absolute_without_resolving_links(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _validate_agent_page_metadata(document: MemoryDocument, path: str) -> None:
    if unicode_chars(document.description) > MAX_DESCRIPTION_CHARS:
        raise MemoryValidationError(
            "invalid_entry",
            f"{path} description exceeds {MAX_DESCRIPTION_CHARS} characters",
            path=path,
            recovery="Shorten the description before changing this page's metadata.",
        )
    if len(document.aliases) > MAX_ALIASES_PER_PAGE:
        raise MemoryValidationError(
            "invalid_entry",
            f"{path} aliases exceed {MAX_ALIASES_PER_PAGE} values",
            path=path,
            recovery="Reduce aliases before changing this page's metadata.",
        )


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


def _prepare_dynamic_directories(root: Path, created_directories: list[Path]) -> None:
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


class MemoryStore:
    def __init__(self, root: Path, _config: MemoryFilesConfig):
        self.root = _absolute_without_resolving_links(root)
        self.lock_path = self.root / ".keepygaga.lock"
        self.lock = FileLock(str(self.lock_path), timeout=30)

    def list_files(self, scope: MemoryScope) -> dict[str, object]:
        return self._run_locked(lambda: self._list_locked(scope))

    def read(self, paths: list[str]) -> dict[str, object]:
        return self._run_locked(lambda: self._read_locked(paths))

    def create(self, operations: list[CreateOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._create_locked(operations))

    def add(self, operations: list[AddOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._add_locked(operations))

    def update(self, operations: list[UpdateOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._update_locked(operations))

    def move(self, operations: list[MoveOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._move_locked(operations))

    def rename(self, operations: list[RenameOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._rename_locked(operations))

    def delete(self, operations: list[DeleteOperation]) -> dict[str, object]:
        return self._run_locked(lambda: self._delete_locked(operations))

    def inspect(self) -> dict[str, object]:
        return self._run_locked(self._inspect_locked)

    def _run_locked(
        self, callback: Callable[[], dict[str, object]]
    ) -> dict[str, object]:
        if _is_link_like(self.root):
            return {
                "status": "invalid_source",
                "message": f"memory root must not be a symlink or junction: {self.root}",
            }
        if not self.root.is_dir():
            if self.root.exists():
                return {
                    "status": "invalid_source",
                    "message": f"memory root must be a directory: {self.root}",
                }
            return {
                "status": "not_initialized",
                "message": f"memory root does not exist: {self.root}",
            }
        if _is_link_like(self.lock_path):
            return {
                "status": "invalid_source",
                "message": f"memory lock path must not be a symlink: {self.lock_path}",
            }
        try:
            _ensure_private_lock_file(self.lock_path)
            with self.lock:
                return callback()
        except Timeout:
            return {
                "status": "write_conflict",
                "message": "could not acquire the global memory lock",
            }
        except MemoryValidationError as exc:
            return exc.response()
        except PermissionError as exc:
            return {
                "status": "permission_denied",
                "message": f"{type(exc).__name__}: {exc}",
            }
        except (OSError, UnicodeDecodeError) as exc:
            return {
                "status": "read_failed",
                "message": f"{type(exc).__name__}: {exc}",
            }
        except Exception as exc:
            return {
                "status": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
            }

    def _catalog_paths(self, *, require_complete: bool = True) -> list[str]:
        missing: list[str] = []
        self._validate_catalog_directories(missing)
        paths = self._fixed_catalog_paths(missing)
        paths.extend(self._dynamic_catalog_paths())
        if missing and require_complete:
            raise MemoryValidationError(
                "not_initialized",
                "memory tree is not initialized: " + ", ".join(missing),
            )
        return paths

    def _validate_catalog_directories(self, missing: list[str]) -> None:
        for directory_name in DYNAMIC_DIRS:
            directory = self.root / directory_name
            if _is_link_like(directory):
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory directory must not be a symlink: {directory}",
                )
            if directory.exists() and not directory.is_dir():
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path must be a directory: {directory}",
                )
            if not directory.exists():
                missing.append(str(directory))

    def _fixed_catalog_paths(self, missing: list[str]) -> list[str]:
        paths: list[str] = []
        for relative in FIXED_PATHS:
            target = self.root / relative
            if _is_link_like(target):
                raise MemoryValidationError(
                    "invalid_source", f"memory path must not be a symlink: {target}"
                )
            if target.is_file():
                paths.append(relative)
            elif target.exists():
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path must be a regular file: {target}",
                    path=relative,
                )
            else:
                missing.append(str(target))
        return paths

    def _dynamic_catalog_paths(self, scope: str | None = None) -> list[str]:
        paths: list[str] = []
        directory_names = (scope,) if scope is not None else DYNAMIC_DIRS
        for directory_name in directory_names:
            directory = self.root / directory_name
            if not directory.is_dir():
                continue
            markdown_targets = (
                target for target in directory.iterdir() if target.suffix == ".md"
            )
            for target in sorted(markdown_targets, key=lambda item: item.name):
                if _is_link_like(target) or not target.is_file():
                    relative = f"{directory_name}/{target.name}"
                    raise MemoryValidationError(
                        "invalid_source",
                        f"memory path must be a regular file: {target}",
                        path=relative,
                        repairable=False,
                        recovery=(
                            "Replace the exact path with a regular UTF-8 Markdown file."
                        ),
                    )
                paths.append(f"{directory_name}/{target.name}")
        return paths

    def _load_catalog(
        self,
        *,
        require_complete: bool = True,
    ) -> dict[str, LoadedFile]:
        files: dict[str, LoadedFile] = {}
        for relative in self._catalog_paths(require_complete=require_complete):
            target = self.root / relative
            text = normalize_text(self._read_catalog_text(target, relative))
            files[relative] = LoadedFile(
                path=relative,
                document=parse_memory_file(text, relative),
                text=text,
                version=sha256_text(text),
            )
        _validate_catalog(files)
        return files

    def _read_catalog_text(
        self, target: Path, relative: str, *, max_chars: int | None = None
    ) -> str:
        try:
            descriptor = self._open_catalog_descriptor(target, relative)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR) or _is_link_like(target):
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path and its dynamic directory must not be symlinks: {target}",
                    path=relative,
                ) from exc
            raise
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path must be a regular file: {target}",
                    path=relative,
                )
            with os.fdopen(descriptor, encoding="utf-8") as handle:
                descriptor = -1
                text = handle.read() if max_chars is None else handle.read(max_chars + 1)
                if max_chars is not None and len(text) > max_chars:
                    raise MemoryValidationError(
                        "capacity_exceeded",
                        f"{relative} exceeds the bounded repair input",
                        path=relative,
                        limit=max_chars,
                        repairable=False,
                        recovery="Organize the invalid page manually before retrying.",
                    )
                return text
        except UnicodeDecodeError as exc:
            raise MemoryValidationError(
                "invalid_source",
                f"{relative} must be valid UTF-8",
                path=relative,
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _open_catalog_descriptor(self, target: Path, relative: str) -> int:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if os.open not in os.supports_dir_fd or not hasattr(os, "O_DIRECTORY"):
            if _is_link_like(target) or _is_link_like(target.parent):
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path and its dynamic directory must not be symlinks: {target}",
                    path=relative,
                )
            return os.open(target, flags)

        parts = PurePosixPath(relative).parts
        root_descriptor = os.open(
            self.root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        parent_descriptor = -1
        try:
            parent = root_descriptor
            if len(parts) == 2:
                parent_descriptor = os.open(
                    parts[0],
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root_descriptor,
                )
                parent = parent_descriptor
            return os.open(parts[-1], flags, dir_fd=parent)
        finally:
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
            os.close(root_descriptor)

    def _list_locked(self, scope: MemoryScope) -> dict[str, object]:
        if scope not in DYNAMIC_DIRS:
            raise MemoryValidationError(
                "invalid_entry", "scope must be topics, areas, or people"
            )
        directory = self.root / scope
        if _is_link_like(directory) or (directory.exists() and not directory.is_dir()):
            raise MemoryValidationError(
                "invalid_source",
                f"memory path must be a directory: {directory}",
                path=scope,
                repairable=False,
                recovery="Replace the exact scope path with a regular directory.",
            )
        if not directory.is_dir():
            raise MemoryValidationError(
                "not_initialized",
                f"memory directory does not exist: {directory}",
                path=scope,
                repairable=False,
                recovery="Initialize the Memory Root, then call list again.",
            )
        listing: list[dict[str, object]] = []
        for path in self._dynamic_catalog_paths(scope):
            target = self.root / path
            try:
                text = normalize_text(self._read_catalog_text(target, path))
            except MemoryValidationError as exc:
                raise MemoryValidationError(
                    exc.status,
                    str(exc),
                    path=exc.path or path,
                    repairable=False,
                    recovery=(
                        exc.recovery
                        or "Fix the exact page manually, then call list again."
                    ),
                ) from exc
            try:
                document = parse_page_metadata(text, path)
            except MemoryValidationError as exc:
                if unicode_chars(text) > MAX_REPAIR_INPUT_CHARS:
                    repairable = False
                    recovery = (
                        "The invalid page is above the bounded repair input; organize it manually, "
                        "then call list again."
                    )
                else:
                    try:
                        repaired_document = repair_memory_file(text, path)
                    except MemoryValidationError:
                        repairable = False
                        recovery = "Fix the exact page manually, then call list again."
                    else:
                        repaired_used = unicode_chars(
                            render_memory_file(repaired_document, path)
                        )
                        used = unicode_chars(text)
                        limit = page_limit(path)
                        repairable = repaired_used <= limit or (
                            used > limit and repaired_used < used
                        )
                        recovery = (
                            "Call update with target=repair, this path, and the returned "
                            "version; stop and report any conflict."
                            if repairable
                            else "Organize the page manually within its capacity, then call list again."
                        )
                raise MemoryValidationError(
                    exc.status,
                    str(exc),
                    path=path,
                    repairable=repairable,
                    recovery=recovery,
                    raw=text if repairable else None,
                    version=sha256_text(text) if repairable else None,
                ) from exc
            listing.append(
                {
                    "path": path,
                    "description": document.description,
                    "aliases": list(document.aliases),
                }
            )
        return {"status": "ok", "files": listing}

    def _read_locked(self, paths: list[str]) -> dict[str, object]:
        if not paths or len(paths) > MAX_READ_PATHS:
            raise MemoryValidationError(
                "invalid_entry",
                f"paths must contain between 1 and {MAX_READ_PATHS} paths",
            )
        canonical = [canonical_memory_path(path) for path in paths]
        if len(canonical) != len(set(canonical)):
            raise MemoryValidationError(
                "invalid_entry", "paths must not contain duplicates"
            )
        files: dict[str, LoadedFile] = {}
        for path in canonical:
            target = self.root / path
            if _is_link_like(target):
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path must not be a symlink: {path}",
                    path=path,
                    repairable=False,
                    recovery="Replace the exact path with a regular UTF-8 Markdown file.",
                )
            if not target.is_file():
                raise MemoryValidationError(
                    "not_found", f"memory file not found: {path}", path=path
                )
            text = normalize_text(self._read_catalog_text(target, path))
            files[path] = LoadedFile(
                path=path,
                document=parse_memory_file(text, path),
                text=text,
                version=sha256_text(text),
            )
        return {
            "status": "ok",
            "files": [
                self._read_item(self._require_existing(files, path))
                for path in canonical
            ],
        }

    def _inspect_locked(self) -> dict[str, object]:
        files = self._load_catalog()
        capacities = {
            str(self.root / path): {
                "used": unicode_chars(loaded.text),
                "limit": page_limit(path),
                "over_limit": unicode_chars(loaded.text) > page_limit(path),
            }
            for path, loaded in files.items()
        }
        dynamic_pages = {
            scope: sum(1 for path in files if path.startswith(f"{scope}/"))
            for scope in DYNAMIC_DIRS
        }
        page_limit_exceeded = {
            scope: dynamic_pages[scope] > DYNAMIC_PAGE_LIMITS[scope]
            for scope in DYNAMIC_DIRS
        }
        permission_warnings = self._permission_warnings()
        return {
            "status": "ok",
            "capacities": capacities,
            "split_recommended": any(
                bool(item["over_limit"]) for item in capacities.values()
            ),
            "dynamic_pages": dynamic_pages,
            "max_dynamic_pages": dict(DYNAMIC_PAGE_LIMITS),
            "dynamic_page_limit_exceeded": page_limit_exceeded,
            "permission_warnings": permission_warnings,
        }

    def _create_locked(self, operations: list[CreateOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        mutation_date = _local_date()
        for operation in operations:
            path = canonical_memory_path(operation.path)
            if not is_dynamic_path(path):
                raise MemoryValidationError(
                    "invalid_path", "create path must be dynamic", path=path
                )
            if path in working:
                raise MemoryValidationError("already_exists", f"page exists: {path}")
            document = MemoryDocument(
                name=PurePosixPath(path).stem,
                description=operation.description,
                aliases=tuple(operation.aliases),
                facts=tuple(
                    stored_fact(fact, date=mutation_date) for fact in operation.facts
                ),
            )
            _validate_agent_page_metadata(document, path)
            working[path] = self._loaded(path, document)
            mutations.append(
                self._mutation(
                    "create", "page", path, [fact.content for fact in document.facts]
                )
            )
        return self._finish(initial, working, mutations)

    def _add_locked(self, operations: list[AddOperation]) -> dict[str, object]:
        self._require_operations(operations)
        self._check_duplicate_targets([op.path for op in operations])
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        mutation_date = _local_date()
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            document = MemoryDocument(
                name=current.document.name,
                description=current.document.description,
                aliases=current.document.aliases,
                facts=(
                    *current.document.facts,
                    *(
                        stored_fact(fact, date=mutation_date)
                        for fact in operation.facts
                    ),
                ),
            )
            working[current.path] = self._loaded(current.path, document)
            mutations.append(
                self._mutation(
                    "add",
                    "fact",
                    current.path,
                    [fact.content for fact in operation.facts],
                )
            )
        return self._finish(initial, working, mutations)

    def _update_locked(self, operations: list[UpdateOperation]) -> dict[str, object]:
        self._require_operations(operations)
        repair_operations = [
            operation
            for operation in operations
            if isinstance(operation, RepairPageOperation)
        ]
        if repair_operations:
            if len(repair_operations) != len(operations):
                raise MemoryValidationError(
                    "invalid_entry",
                    "repair operations cannot be mixed with other updates",
                )
            return self._repair_locked(repair_operations)
        self._check_duplicate_targets([op.path for op in operations])
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        mutation_date = _local_date()
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            if isinstance(operation, UpdatePageOperation):
                document = MemoryDocument(
                    name=current.document.name,
                    description=operation.description or current.document.description,
                    aliases=(
                        tuple(operation.aliases)
                        if operation.aliases is not None
                        else current.document.aliases
                    ),
                    facts=current.document.facts,
                )
                _validate_agent_page_metadata(document, current.path)
                contents = [
                    value
                    for value in (operation.description, *(operation.aliases or []))
                    if value
                ]
                target = "page"
            else:
                assert isinstance(operation, UpdateFactOperation)
                if (
                    operation.old_fact.basis == "stated"
                    and operation.new_fact.basis != "stated"
                ):
                    raise MemoryValidationError(
                        "invalid_entry", "stated facts cannot be downgraded to observed"
                    )
                facts = list(current.document.facts)
                try:
                    index = next(
                        index
                        for index, fact in enumerate(facts)
                        if fact_key(fact) == fact_key(operation.old_fact)
                    )
                except StopIteration as exc:
                    raise MemoryValidationError(
                        "not_found",
                        f"fact not found in {current.path}",
                        path=current.path,
                    ) from exc
                facts[index] = stored_fact(operation.new_fact, date=mutation_date)
                document = MemoryDocument(
                    name=current.document.name,
                    description=current.document.description,
                    aliases=current.document.aliases,
                    facts=tuple(facts),
                )
                contents = [operation.new_fact.content]
                target = "fact"
            working[current.path] = self._loaded(current.path, document)
            mutations.append(self._mutation("update", target, current.path, contents))
        return self._finish(initial, working, mutations)

    def _repair_locked(
        self, operations: list[RepairPageOperation]
    ) -> dict[str, object]:
        self._check_duplicate_targets([operation.path for operation in operations])
        initial: dict[str, LoadedFile] = {}
        working: dict[str, LoadedFile] = {}
        mutations: list[dict[str, object]] = []
        for operation in operations:
            path = canonical_memory_path(operation.path)
            if not is_dynamic_path(path):
                raise MemoryValidationError(
                    "invalid_path",
                    "repair is available only for dynamic pages proposed by scoped list",
                    path=path,
                    repairable=False,
                    recovery=(
                        "Fix the Home Page manually and preserve its current versioned content."
                    ),
                )
            if not VERSION_RE.fullmatch(operation.if_version):
                raise MemoryValidationError("invalid_entry", "if_version is invalid")
            target = self.root / path
            try:
                text = normalize_text(
                    self._read_catalog_text(
                        target, path, max_chars=MAX_REPAIR_INPUT_CHARS
                    )
                )
            except FileNotFoundError as exc:
                raise MemoryValidationError(
                    "not_found",
                    f"repair target no longer exists: {path}",
                    path=path,
                    recovery=(
                        "Call list for the same scope again; do not retry the stale repair."
                    ),
                ) from exc
            version = sha256_text(text)
            if version != operation.if_version:
                raise MemoryValidationError(
                    "write_conflict",
                    f"memory file changed since repair was proposed: {path}",
                    path=path,
                    version=version,
                    recovery=(
                        "Call list for the same scope again and only retry if the page "
                        "is still explicitly marked repairable."
                    ),
                )
            try:
                parse_page_metadata(text, path)
            except MemoryValidationError:
                pass
            else:
                raise MemoryValidationError(
                    "invalid_entry",
                    f"repair target is already structurally valid: {path}",
                    path=path,
                    repairable=False,
                    recovery=(
                        "Do not repair this page; use a normal versioned mutation only "
                        "when its memory content needs to change."
                    ),
                )
            document = repair_memory_file(text, path)
            initial[path] = LoadedFile(
                path=path,
                document=document,
                text=text,
                version=version,
            )
            working[path] = self._loaded(path, document)
            mutations.append(self._mutation("repair", "page", path, []))
        return self._finish(initial, working, mutations)

    def _move_locked(self, operations: list[MoveOperation]) -> dict[str, object]:
        self._require_operations(operations)
        move_paths = [operation.source_path for operation in operations]
        move_paths.extend(
            operation.destination_path or operation.new_path or ""
            for operation in operations
        )
        self._check_duplicate_targets(
            move_paths,
            recovery=(
                "Combine all exact Facts for one source/destination pair into one "
                "operation; each page may appear in only one move operation."
            ),
        )
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        for operation in operations:
            source = self._check_version(
                working, operation.source_path, operation.source_version
            )
            if operation.destination_path is not None:
                assert operation.destination_version is not None
                destination = self._check_version(
                    working, operation.destination_path, operation.destination_version
                )
                if source.path == destination.path:
                    raise MemoryValidationError(
                        "invalid_entry", "source and destination must differ"
                    )
                destination_path = destination.path
                destination_document = destination.document
            else:
                assert operation.new_path is not None
                assert operation.description is not None
                assert operation.aliases is not None
                destination_path = canonical_memory_path(operation.new_path)
                if not is_dynamic_path(destination_path):
                    raise MemoryValidationError(
                        "invalid_path",
                        "new move destination must be dynamic",
                        path=destination_path,
                    )
                if destination_path in working:
                    raise MemoryValidationError(
                        "already_exists", f"page exists: {destination_path}"
                    )
                destination_document = MemoryDocument(
                    name=PurePosixPath(destination_path).stem,
                    description=operation.description,
                    aliases=tuple(operation.aliases),
                    facts=(),
                )
                _validate_agent_page_metadata(destination_document, destination_path)
            source_facts = list(source.document.facts)
            moved_facts: list[StoredFact] = []
            for requested_fact in operation.facts:
                try:
                    index = next(
                        index
                        for index, source_fact in enumerate(source_facts)
                        if fact_key(source_fact) == fact_key(requested_fact)
                    )
                except StopIteration as exc:
                    raise MemoryValidationError(
                        "not_found",
                        f"requested fact not found in {source.path}",
                        path=source.path,
                        recovery=(
                            "Copy every requested Fact exactly from the latest source "
                            "Page Snapshot and retry the whole operation."
                        ),
                    ) from exc
                moved_facts.append(source_facts.pop(index))
            if not source_facts:
                raise MemoryValidationError(
                    "invalid_entry",
                    "move must leave at least one Fact in the source page",
                    path=source.path,
                    recovery=(
                        "Rename or update the source page instead, or request an authorized "
                        "page deletion if the source should no longer exist."
                    ),
                )
            working[source.path] = self._loaded(
                source.path,
                MemoryDocument(
                    name=source.document.name,
                    description=source.document.description,
                    aliases=source.document.aliases,
                    facts=tuple(source_facts),
                ),
            )
            working[destination_path] = self._loaded(
                destination_path,
                MemoryDocument(
                    name=destination_document.name,
                    description=destination_document.description,
                    aliases=destination_document.aliases,
                    facts=(*destination_document.facts, *moved_facts),
                ),
            )
            mutations.append(
                self._mutation(
                    "move",
                    f"{source.path} -> {destination_path}",
                    source.path,
                    [fact.content for fact in moved_facts],
                )
            )
        return self._finish(initial, working, mutations)

    def _rename_locked(self, operations: list[RenameOperation]) -> dict[str, object]:
        self._require_operations(operations)
        rename_paths = [canonical_memory_path(op.path) for op in operations]
        rename_paths.extend(canonical_memory_path(op.new_path) for op in operations)
        self._check_duplicate_targets(rename_paths)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        renamed_from: dict[str, str] = {}
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            if not is_dynamic_path(current.path):
                raise MemoryValidationError(
                    "invalid_path", "rename source must be dynamic", path=current.path
                )
            new_path = canonical_memory_path(operation.new_path)
            if not is_dynamic_path(new_path):
                raise MemoryValidationError(
                    "invalid_path", "rename destination must be dynamic", path=new_path
                )
            if new_path in working:
                raise MemoryValidationError(
                    "already_exists", f"page exists: {new_path}"
                )
            new_name = PurePosixPath(new_path).stem
            aliases = [
                alias
                for alias in current.document.aliases
                if _identity(alias) != _identity(new_name)
            ]
            old_name_identity = _identity(current.document.name)
            if old_name_identity != _identity(new_name) and old_name_identity not in {
                _identity(alias) for alias in aliases
            }:
                if len(aliases) >= MAX_ALIASES_PER_PAGE:
                    raise MemoryValidationError(
                        "capacity_exceeded",
                        "rename cannot preserve the old page name within the alias limit",
                        path=current.path,
                        current=len(aliases),
                        limit=MAX_ALIASES_PER_PAGE,
                        recovery=(
                            "Update aliases to leave one slot for the old page name, "
                            "then retry against the latest Page Snapshot."
                        ),
                    )
                aliases.append(current.document.name)
            document = MemoryDocument(
                name=new_name,
                description=current.document.description,
                aliases=tuple(aliases),
                facts=current.document.facts,
            )
            _validate_agent_page_metadata(document, new_path)
            del working[current.path]
            working[new_path] = self._loaded(new_path, document)
            renamed_from[new_path] = current.path
            mutations.append(self._mutation("rename", "page", current.path, [new_path]))
        return self._finish(
            initial, working, mutations, renamed_from=renamed_from
        )

    def _delete_locked(self, operations: list[DeleteOperation]) -> dict[str, object]:
        self._require_operations(operations)
        self._check_duplicate_targets([op.path for op in operations])
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            if isinstance(operation, DeletePageOperation):
                if not is_dynamic_path(current.path):
                    raise MemoryValidationError(
                        "invalid_path",
                        "only dynamic pages may be deleted",
                        path=current.path,
                    )
                del working[current.path]
                contents = ["page"]
                target = "page"
            else:
                facts = list(current.document.facts)
                try:
                    index = next(
                        index
                        for index, fact in enumerate(facts)
                        if fact_key(fact) == fact_key(operation.fact)
                    )
                except StopIteration as exc:
                    raise MemoryValidationError(
                        "not_found",
                        f"fact not found in {current.path}",
                        path=current.path,
                    ) from exc
                facts.pop(index)
                working[current.path] = self._loaded(
                    current.path,
                    MemoryDocument(
                        name=current.document.name,
                        description=current.document.description,
                        aliases=current.document.aliases,
                        facts=tuple(facts),
                    ),
                )
                contents = [operation.fact.content]
                target = "fact"
            mutations.append(self._mutation("delete", target, current.path, contents))
        return self._finish(initial, working, mutations)

    def _finish(
        self,
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
        mutations: list[dict[str, object]],
        *,
        renamed_from: dict[str, str] | None = None,
    ) -> dict[str, object]:
        _validate_catalog(working)
        self._validate_scope_capacity(initial, working)
        self._validate_page_capacity(
            initial, working, mutations, renamed_from or {}
        )
        changed_paths = sorted(
            path
            for path in set(initial) | set(working)
            if path not in initial
            or path not in working
            or initial[path].text != working[path].text
        )
        if not changed_paths:
            raise MemoryValidationError(
                "invalid_entry", "mutation would not change memory"
            )
        self._commit(initial, working, changed_paths)
        return {
            "status": "applied",
            "mutations": mutations,
            "files": [
                self._read_item(working[path])
                for path in changed_paths
                if path in working
            ],
        }

    @staticmethod
    def _validate_scope_capacity(
        initial: dict[str, LoadedFile], working: dict[str, LoadedFile]
    ) -> None:
        for scope, limit in DYNAMIC_PAGE_LIMITS.items():
            before = sum(1 for path in initial if path.startswith(f"{scope}/"))
            after = sum(1 for path in working if path.startswith(f"{scope}/"))
            if after > limit and after > before:
                raise MemoryValidationError(
                    "capacity_exceeded",
                    f"{scope} page count would exceed {limit}: current {before}, proposed {after}",
                    scope=scope,
                    current=before,
                    limit=limit,
                    recovery=(
                        f"Reuse or organize an existing {scope} page; if none is suitable, "
                        "ask the user to organize that memory scope."
                    ),
                )

    @staticmethod
    def _validate_page_capacity(
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
        mutations: list[dict[str, object]],
        renamed_from: dict[str, str],
    ) -> None:
        mutation_by_path = {
            str(mutation["path"]): mutation for mutation in mutations
        }
        for path, after in working.items():
            source_path = renamed_from.get(path)
            before = initial.get(source_path or path)
            if before is not None and before.text == after.text:
                continue
            used = unicode_chars(after.text)
            limit = page_limit(path)
            if used <= limit:
                continue
            if before is not None:
                before_used = unicode_chars(before.text)
                mutation = mutation_by_path.get(source_path or path)
                action = mutation.get("action") if mutation is not None else None
                target = mutation.get("target") if mutation is not None else None
                if action == "repair" and before_used > limit and used < before_used:
                    continue
                canonical_before_used = unicode_chars(
                    render_memory_file(before.document, source_path or path)
                )
                reduces_fact_content = (
                    (action == "update" and target == "fact")
                    or (action == "delete" and target == "fact")
                    or action == "move"
                )
                if (
                    canonical_before_used > limit
                    and used < canonical_before_used
                    and (
                        source_path is not None
                        or not is_dynamic_path(path)
                        or reduces_fact_content
                    )
                ):
                    continue
            dynamic = is_dynamic_path(path)
            recovery = (
                "Organize exact Facts into a suitable existing page or a bounded new "
                "page, then retry against the latest Page Snapshots."
                if dynamic
                else "Refine the proposed Fact or ask the user which existing memory to remove."
            )
            raise MemoryValidationError(
                "capacity_exceeded",
                f"{path} would use {used} characters, above its {limit} character limit",
                path=path,
                current=used,
                limit=limit,
                recovery=recovery,
            )

    def _commit(
        self,
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
        changed_paths: list[str],
    ) -> None:
        staged: dict[str, Path] = {}
        try:
            self._stage_commit(working, changed_paths, staged)
            self._apply_commit(initial, working, changed_paths, staged)
        except MemoryValidationError:
            raise
        except Exception as exc:
            raise MemoryValidationError(
                "write_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        finally:
            for temporary in staged.values():
                with suppress(FileNotFoundError):
                    temporary.unlink()

    def _stage_commit(
        self,
        working: dict[str, LoadedFile],
        changed_paths: list[str],
        staged: dict[str, Path],
    ) -> None:
        for relative in changed_paths:
            self._assert_parent_safe(relative)
            after = working.get(relative)
            if after is None:
                continue
            target = self.root / relative
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(after.text)
                handle.flush()
                os.fsync(handle.fileno())
                staged[relative] = Path(handle.name)

    def _apply_commit(
        self,
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
        changed_paths: list[str],
        staged: dict[str, Path],
    ) -> None:
        applied_paths: list[str] = []
        try:
            ordered_paths = sorted(
                changed_paths,
                key=lambda path: self._commit_priority(
                    initial.get(path), working.get(path), path
                ),
            )
            for relative in ordered_paths:
                self._verify_live_versions(initial, [relative])
                target = self.root / relative
                if relative not in working:
                    target.unlink()
                else:
                    temporary = staged[relative]
                    if relative in initial:
                        mode = target.stat(follow_symlinks=False).st_mode & 0o7777
                        os.chmod(temporary, mode)
                    else:
                        _chmod_private_file(temporary)
                    os.replace(temporary, target)
                    del staged[relative]
                applied_paths.append(relative)
        except MemoryValidationError as exc:
            if not applied_paths:
                raise
            raise MemoryValidationError(
                "partial_commit",
                f"batch stopped after some files were applied: {exc}",
                path=exc.path,
                latest=exc.latest,
                applied_paths=applied_paths,
            ) from exc
        except Exception as exc:
            status = "partial_commit" if applied_paths else "write_failed"
            raise MemoryValidationError(
                status,
                f"{type(exc).__name__}: {exc}",
                applied_paths=applied_paths,
            ) from exc

    @staticmethod
    def _commit_priority(
        before: LoadedFile | None,
        after: LoadedFile | None,
        path: str,
    ) -> tuple[int, str]:
        if after is None:
            return 2, path
        if before is None or len(after.document.facts) >= len(before.document.facts):
            return 0, path
        return 1, path

    def _verify_live_versions(
        self,
        initial: dict[str, LoadedFile],
        changed_paths: list[str],
    ) -> None:
        for relative in changed_paths:
            target = self.root / relative
            before = initial.get(relative)
            if before is None:
                if target.exists() or _is_link_like(target):
                    raise MemoryValidationError(
                        "write_conflict",
                        f"memory path appeared during mutation: {relative}",
                    )
                continue
            try:
                text = normalize_text(self._read_catalog_text(target, relative))
            except FileNotFoundError as exc:
                raise MemoryValidationError(
                    "write_conflict",
                    f"memory path disappeared during mutation: {relative}",
                ) from exc
            if sha256_text(text) != before.version:
                raise MemoryValidationError(
                    "write_conflict", f"memory file changed during mutation: {relative}"
                )

    def _assert_parent_safe(self, relative: str) -> None:
        canonical = canonical_memory_path(relative)
        parent = (self.root / canonical).parent
        if _is_link_like(parent) or not parent.is_dir():
            raise MemoryValidationError(
                "write_conflict",
                f"memory parent directory is unsafe: {parent}",
                path=canonical,
            )

    def _loaded(self, path: str, document: MemoryDocument) -> LoadedFile:
        text = render_memory_file(document, path)
        return LoadedFile(
            path=path,
            document=validate_document(document, path),
            text=text,
            version=sha256_text(text),
        )

    def _read_item(self, loaded: LoadedFile) -> dict[str, object]:
        item: dict[str, object] = {
            "path": loaded.path,
            "name": loaded.document.name,
            "description": loaded.document.description,
            "aliases": list(loaded.document.aliases),
            "facts": [fact.model_dump() for fact in loaded.document.facts],
            "version": loaded.version,
        }
        if unicode_chars(loaded.text) > page_limit(loaded.path):
            item["split_recommended"] = True
        return item

    def _require_existing(self, files: dict[str, LoadedFile], path: str) -> LoadedFile:
        canonical = canonical_memory_path(path)
        loaded = files.get(canonical)
        if loaded is None:
            raise MemoryValidationError(
                "not_found", f"memory file not found: {canonical}", path=canonical
            )
        return loaded

    def _check_version(
        self, files: dict[str, LoadedFile], path: str, expected: str
    ) -> LoadedFile:
        if not VERSION_RE.fullmatch(expected):
            raise MemoryValidationError("invalid_entry", "if_version is invalid")
        loaded = self._require_existing(files, path)
        if loaded.version != expected:
            raise MemoryValidationError(
                "write_conflict",
                f"memory file changed since it was read: {loaded.path}",
                path=loaded.path,
                latest=self._read_item(loaded),
            )
        return loaded

    def _permission_warnings(self) -> list[dict[str, object]]:
        if not _posix_mode_supported():
            return []
        warnings: list[dict[str, object]] = []
        candidates: list[tuple[Path, bool]] = [
            (self.root, True),
            (self.lock_path, False),
            *((self.root / directory, True) for directory in DYNAMIC_DIRS),
            *((self.root / relative, False) for relative in FIXED_PATHS),
        ]
        for directory_name in DYNAMIC_DIRS:
            directory = self.root / directory_name
            if not directory.is_dir():
                continue
            markdown_targets = (
                target for target in directory.iterdir() if target.suffix == ".md"
            )
            for target in sorted(markdown_targets, key=lambda item: item.name):
                if target.is_file() and not _is_link_like(target):
                    candidates.append((target, False))
        for target, directory in candidates:
            if not target.exists() or _is_link_like(target):
                continue
            mode = target.stat(follow_symlinks=False).st_mode & 0o777
            if _permission_too_open(mode, directory=directory):
                warnings.append(
                    {
                        "path": str(target),
                        "mode": oct(mode),
                        "expected": oct(
                            NEW_DIRECTORY_MODE if directory else NEW_FILE_MODE
                        ),
                    }
                )
        return warnings

    @staticmethod
    def _require_operations(operations: Sequence[object]) -> None:
        if not operations or len(operations) > MAX_MUTATION_OPERATIONS:
            raise MemoryValidationError(
                "invalid_entry",
                f"operations must contain between 1 and {MAX_MUTATION_OPERATIONS} operations",
            )

    @staticmethod
    def _check_duplicate_targets(
        paths: Sequence[str], *, recovery: str | None = None
    ) -> None:
        seen: set[str] = set()
        for path in paths:
            if path in seen:
                raise MemoryValidationError(
                    "duplicate_target",
                    f"path appears more than once in this batch: {path}",
                    path=path,
                    recovery=recovery,
                )
            seen.add(path)

    @staticmethod
    def _mutation(
        action: str, target: str, path: str, contents: Sequence[str]
    ) -> dict[str, object]:
        return {
            "action": action,
            "target": target,
            "path": path,
            "receipt": receipt(action, path, contents),
        }


def _validate_catalog(files: dict[str, LoadedFile]) -> None:
    for path, loaded in files.items():
        canonical_memory_path(path)
        validate_document(loaded.document, path)
