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

from filelock import FileLock, Timeout

from keepygaga.codec import (
    MemoryDocument,
    StoredFact,
    _identity,
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
from keepygaga.memory_contract import (
    MAX_ALIASES_PER_PAGE,
    MAX_DESCRIPTION_CHARS,
    MAX_MUTATION_OPERATIONS,
    MAX_READ_PATHS,
    NEW_DIRECTORY_MODE,
    NEW_FILE_MODE,
    AddOperation,
    CreateOperation,
    DeleteOperation,
    DeletePageOperation,
    MemoryScope,
    MoveOperation,
    RenameOperation,
    RepairPageOperation,
    UpdateFactOperation,
    UpdateOperation,
    UpdatePageOperation,
)
from keepygaga.memory_files import (
    _absolute_without_resolving_links,
    _chmod_private_file,
    _ensure_private_lock_file,
    _is_link_like,
    _permission_too_open,
    _posix_mode_supported,
)
from keepygaga.paths import (
    DYNAMIC_DIRS,
    FIXED_PATHS,
    canonical_memory_path,
    is_dynamic_path,
)

VERSION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class LoadedFile:
    path: str
    document: MemoryDocument
    text: str
    version: str


def _local_date() -> str:
    return calendar_date.today().isoformat()


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


def _with_page_changes(
    document: MemoryDocument,
    path: str,
    *,
    description: str | None = None,
    aliases: Sequence[str] | None = None,
    facts: Sequence[StoredFact] | None = None,
) -> MemoryDocument:
    changed = MemoryDocument(
        name=document.name,
        description=description if description is not None else document.description,
        aliases=tuple(aliases) if aliases is not None else document.aliases,
        facts=tuple(facts) if facts is not None else document.facts,
    )
    if description is not None or aliases is not None:
        _validate_agent_page_metadata(changed, path)
    return changed


class MemoryStore:
    def __init__(self, root: Path, _config: MemoryFilesConfig):
        self.root = _absolute_without_resolving_links(root)
        self.limits = _config.limits
        self.lock_path = self.root / ".keepygaga.lock"
        self.lock = FileLock(str(self.lock_path), timeout=30)

    def _page_limit(self, path: str) -> int:
        if path in FIXED_PATHS:
            return self.limits.fixed_page_chars
        return self.limits.dynamic_page_chars

    def _repair_input_limit(self) -> int:
        return self.limits.dynamic_page_chars * 2

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
                if unicode_chars(text) > self._repair_input_limit():
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
                        limit = self._page_limit(path)
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
                "limit": self._page_limit(path),
                "over_limit": unicode_chars(loaded.text) > self._page_limit(path),
            }
            for path, loaded in files.items()
        }
        dynamic_pages = {
            scope: sum(1 for path in files if path.startswith(f"{scope}/"))
            for scope in DYNAMIC_DIRS
        }
        page_limit_exceeded = {
            scope: dynamic_pages[scope] > limit
            for scope, limit in self.limits.dynamic_pages().items()
        }
        permission_warnings = self._permission_warnings()
        return {
            "status": "ok",
            "capacities": capacities,
            "split_recommended": any(
                bool(item["over_limit"]) for item in capacities.values()
            ),
            "dynamic_pages": dynamic_pages,
            "max_dynamic_pages": self.limits.dynamic_pages(),
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
            document = _with_page_changes(
                current.document,
                current.path,
                description=operation.description,
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
                document = _with_page_changes(
                    current.document,
                    current.path,
                    description=operation.description,
                    aliases=operation.aliases,
                )
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
                document = _with_page_changes(
                    current.document,
                    current.path,
                    description=operation.description,
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
                        target, path, max_chars=self._repair_input_limit()
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
                destination_document = _with_page_changes(
                    destination.document,
                    destination.path,
                    description=operation.description,
                )
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
                _with_page_changes(
                    source.document,
                    source.path,
                    description=operation.source_description,
                    facts=tuple(source_facts),
                ),
            )
            working[destination_path] = self._loaded(
                destination_path,
                _with_page_changes(
                    destination_document,
                    destination_path,
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
                    _with_page_changes(
                        current.document,
                        current.path,
                        description=operation.description,
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

    def _validate_scope_capacity(
        self,
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
    ) -> None:
        for scope, limit in self.limits.dynamic_pages().items():
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

    def _validate_page_capacity(
        self,
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
            limit = self._page_limit(path)
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
        if unicode_chars(loaded.text) > self._page_limit(loaded.path):
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
