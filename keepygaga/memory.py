from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import frontmatter
from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from keepygaga.config import MemoryFilesConfig

Basis = Literal["stated", "observed"]

FIXED_PATHS = ("profile.md", "preferences.md")
DYNAMIC_DIRS = ("topics", "areas", "people")
PROFILE_SOFT_LIMIT = 2000
PREFERENCES_SOFT_LIMIT = 2000
PAGE_SOFT_LIMIT = 8000
MAX_READ_PATHS = 20
MAX_MUTATION_OPERATIONS = 20
MAX_FACTS_PER_OPERATION = 50
MAX_FACT_CONTENT_CHARS = 4096
PROFILE_FACT_CONTENT_LIMIT = 300

DYNAMIC_STEM_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FACT_LINE_RE = re.compile(r"^- \[(stated|observed)\] (.+)$")
FRONTMATTER_KEY_RE = re.compile(r"^(name|description|sources|aliases):")

DEFAULT_DESCRIPTIONS = {
    "profile.md": "用户的稳定身份、背景与长期个人事实。",
    "preferences.md": "用户希望 Agent 如何回应和工作的长期偏好。",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(StrictModel):
    basis: Basis
    content: str = Field(max_length=MAX_FACT_CONTENT_CHARS)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = normalize_text(value).strip()
        if not normalized:
            raise ValueError("fact content must not be empty")
        if "\x00" in normalized or "\n" in normalized:
            raise ValueError("fact content must be one non-empty line")
        return normalized


class CreateOperation(StrictModel):
    path: str
    description: str
    aliases: list[str] = Field(max_length=8)
    facts: list[Fact] = Field(max_length=MAX_FACTS_PER_OPERATION)


class AddOperation(StrictModel):
    path: str
    if_version: str
    facts: list[Fact] = Field(min_length=1, max_length=MAX_FACTS_PER_OPERATION)


class UpdateFactOperation(StrictModel):
    path: str
    if_version: str
    target: Literal["fact"]
    old_fact: Fact
    new_fact: Fact

    @model_validator(mode="after")
    def validate_change(self) -> UpdateFactOperation:
        if _fact_key(self.old_fact) == _fact_key(self.new_fact):
            raise ValueError("old_fact and new_fact must differ")
        return self


class UpdatePageOperation(StrictModel):
    path: str
    if_version: str
    target: Literal["page"]
    description: str | None = None
    aliases: list[str] | None = Field(default=None, max_length=8)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _one_line(value, "description")

    @model_validator(mode="after")
    def validate_change(self) -> UpdatePageOperation:
        if self.description is None and self.aliases is None:
            raise ValueError("page update requires description or aliases")
        return self


class MoveOperation(StrictModel):
    source_path: str
    source_version: str
    destination_path: str
    destination_version: str
    fact: Fact


class RenameOperation(StrictModel):
    path: str
    if_version: str
    new_path: str


class DeleteFactOperation(StrictModel):
    path: str
    if_version: str
    target: Literal["fact"]
    fact: Fact
    authorization: Literal["user_requested"]


class DeletePageOperation(StrictModel):
    path: str
    if_version: str
    target: Literal["page"]
    authorization: Literal["user_requested"]


DeleteOperation = Annotated[
    DeleteFactOperation | DeletePageOperation,
    Field(discriminator="target"),
]
UpdateOperation = Annotated[
    UpdateFactOperation | UpdatePageOperation,
    Field(discriminator="target"),
]

CreateOperations = Annotated[
    list[CreateOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
AddOperations = Annotated[
    list[AddOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
UpdateOperations = Annotated[
    list[UpdateOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
MoveOperations = Annotated[
    list[MoveOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
RenameOperations = Annotated[
    list[RenameOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
DeleteOperations = Annotated[
    list[DeleteOperation], Field(min_length=1, max_length=MAX_MUTATION_OPERATIONS)
]
ReadPaths = Annotated[list[str], Field(min_length=1, max_length=MAX_READ_PATHS)]


@dataclass(frozen=True)
class MemoryDocument:
    name: str
    description: str
    aliases: tuple[str, ...]
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class LoadedFile:
    path: str
    document: MemoryDocument
    text: str
    version: str


class MemoryValidationError(ValueError):
    def __init__(
        self,
        status: str,
        message: str,
        *,
        path: str | None = None,
        latest: dict[str, object] | None = None,
        applied_paths: Sequence[str] | None = None,
    ):
        self.status = status
        self.path = path
        self.latest = latest
        self.applied_paths = list(applied_paths or [])
        super().__init__(message)

    def response(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status, "message": str(self)}
        if self.path is not None:
            payload["path"] = self.path
        if self.latest is not None:
            payload["latest"] = self.latest
        if self.applied_paths:
            payload["applied_paths"] = self.applied_paths
        return payload


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def unicode_chars(text: str) -> int:
    return len(normalize_text(text))


def sha256_text(text: str) -> str:
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _one_line(value: str, field: str) -> str:
    normalized = normalize_text(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if "\x00" in normalized or "\n" in normalized:
        raise ValueError(f"{field} must be one non-empty line")
    return normalized


def _string_array(
    values: object,
    field: str,
    *,
    maximum: int | None = None,
) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(
        isinstance(item, str) for item in values
    ):
        raise MemoryValidationError("invalid_source", f"{field} must be a string array")
    if maximum is not None and len(values) > maximum:
        raise MemoryValidationError(
            "invalid_entry", f"{field} cannot contain more than {maximum} values"
        )
    try:
        normalized = tuple(_one_line(item, field) for item in values)
    except ValueError as exc:
        raise MemoryValidationError("invalid_entry", str(exc)) from exc
    identities = [_identity(item) for item in normalized]
    if len(identities) != len(set(identities)):
        raise MemoryValidationError(
            "invalid_entry", f"{field} contains duplicate values"
        )
    return normalized


def _fact_key(fact: Fact) -> tuple[str, str]:
    return fact.basis, fact.content


def _receipt(action: str, scope: str, contents: Sequence[str]) -> str:
    prefix = f"🧠 {action} [{scope}]"
    text = f"{prefix}: {' · '.join(contents)}" if contents else prefix
    backtick_runs = re.findall(r"`+", text)
    fence = "`" * (max((len(run) for run in backtick_runs), default=0) + 1)
    padding = " " if text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _validate_document(document: MemoryDocument, path: str) -> MemoryDocument:
    expected_name = PurePosixPath(path).stem
    try:
        name = _one_line(document.name, "name")
        description = _one_line(document.description, "description")
    except ValueError as exc:
        raise MemoryValidationError("invalid_entry", str(exc), path=path) from exc
    if name != expected_name:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter name must equal file stem {expected_name!r}",
            path=path,
        )
    aliases = _string_array(list(document.aliases), "aliases", maximum=8)
    if _identity(name) in {_identity(alias) for alias in aliases}:
        raise MemoryValidationError(
            "invalid_entry", f"{path} aliases cannot repeat its name", path=path
        )
    facts = tuple(Fact.model_validate(fact) for fact in document.facts)
    if (
        path == "profile.md"
        and sum(unicode_chars(fact.content) for fact in facts)
        > PROFILE_FACT_CONTENT_LIMIT
    ):
        raise MemoryValidationError(
            "invalid_entry",
            "profile.md Fact.content cannot exceed "
            f"{PROFILE_FACT_CONTENT_LIMIT} characters in total",
            path=path,
        )
    fact_keys = [_fact_key(fact) for fact in facts]
    if len(fact_keys) != len(set(fact_keys)):
        raise MemoryValidationError(
            "invalid_entry", f"{path} contains duplicate facts", path=path
        )
    return MemoryDocument(
        name=name,
        description=description,
        aliases=aliases,
        facts=facts,
    )


def parse_memory_file(text: str, path: str) -> MemoryDocument:
    canonical_memory_path(path)
    normalized = normalize_text(text)
    if not normalized.startswith("---\n"):
        raise MemoryValidationError(
            "invalid_source", f"{path} must begin with YAML frontmatter", path=path
        )
    lines = normalized.splitlines()
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must end with a --- delimiter",
            path=path,
        ) from exc
    field_order = [
        match.group(1)
        for line in lines[1:closing_index]
        if (match := FRONTMATTER_KEY_RE.match(line)) is not None
    ]
    accepted_orders = (
        ["name", "description", "aliases"],
        ["name", "description", "sources", "aliases"],
    )
    if field_order not in accepted_orders:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must contain name, description, aliases in order",
            path=path,
        )
    try:
        post = frontmatter.loads(normalized)
    except Exception as exc:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter could not be parsed: {type(exc).__name__}: {exc}",
            path=path,
        ) from exc
    metadata = dict(post.metadata)
    accepted_keys = (
        ("name", "description", "aliases"),
        ("name", "description", "sources", "aliases"),
    )
    if tuple(metadata) not in accepted_keys:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must contain name, description, aliases in order",
            path=path,
        )
    if not isinstance(metadata["name"], str) or not isinstance(
        metadata["description"], str
    ):
        raise MemoryValidationError(
            "invalid_source", f"{path} name and description must be strings", path=path
        )
    if "sources" in metadata:
        _string_array(metadata["sources"], "sources")
    aliases = _string_array(metadata["aliases"], "aliases", maximum=8)
    facts: list[Fact] = []
    body = normalize_text(post.content).strip()
    if body:
        for line in body.splitlines():
            if not line.strip():
                continue
            match = FACT_LINE_RE.fullmatch(line)
            if match is None:
                raise MemoryValidationError(
                    "invalid_source",
                    f"{path} body may contain only - [stated]/[observed] bullets",
                    path=path,
                )
            basis = match.group(1)
            assert basis in ("stated", "observed")
            facts.append(Fact(basis=basis, content=match.group(2)))
    return _validate_document(
        MemoryDocument(
            name=metadata["name"],
            description=metadata["description"],
            aliases=aliases,
            facts=tuple(facts),
        ),
        path,
    )


def render_memory_file(document: MemoryDocument, path: str) -> str:
    validated = _validate_document(document, path)
    lines = [
        "---",
        f"name: {json.dumps(validated.name, ensure_ascii=False)}",
        f"description: {json.dumps(validated.description, ensure_ascii=False)}",
        "aliases: "
        + json.dumps(
            list(validated.aliases), ensure_ascii=False, separators=(",", ":")
        ),
        "---",
    ]
    if validated.facts:
        lines.append("")
        lines.extend(f"- [{fact.basis}] {fact.content}" for fact in validated.facts)
    return "\n".join(lines).rstrip() + "\n"


def canonical_memory_path(value: str) -> str:
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


def soft_limit(path: str) -> int:
    if path == "profile.md":
        return PROFILE_SOFT_LIMIT
    if path == "preferences.md":
        return PREFERENCES_SOFT_LIMIT
    return PAGE_SOFT_LIMIT


def _default_document(path: str) -> MemoryDocument:
    return MemoryDocument(
        name=PurePosixPath(path).stem,
        description=DEFAULT_DESCRIPTIONS[path],
        aliases=(),
        facts=(),
    )


def initialize_memory_tree(
    root: Path,
    _config: MemoryFilesConfig,
) -> dict[str, object]:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    lock_path = root / ".keepygaga.lock"
    if lock_path.is_symlink():
        raise MemoryValidationError(
            "invalid_source", f"memory lock path must not be a symlink: {lock_path}"
        )
    try:
        with FileLock(str(lock_path), timeout=30):
            for directory in DYNAMIC_DIRS:
                target = root / directory
                if target.is_symlink() or (target.exists() and not target.is_dir()):
                    raise MemoryValidationError(
                        "invalid_source", f"memory path must be a directory: {target}"
                    )
                target.mkdir(exist_ok=True)
            for relative in FIXED_PATHS:
                target = root / relative
                if target.is_symlink():
                    raise MemoryValidationError(
                        "invalid_source", f"memory page must not be a symlink: {target}"
                    )
                if target.exists():
                    continue
                if _exclusive_create(
                    target, render_memory_file(_default_document(relative), relative)
                ):
                    rendered.append(target)
    except Timeout:
        return {
            "status": "write_conflict",
            "message": "could not acquire the global memory lock",
        }
    return {
        "status": "applied" if rendered else "no_op",
        "files": [str(path) for path in rendered],
    }


def _exclusive_create(target: Path, text: str) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return False
    except Exception:
        with suppress(FileNotFoundError):
            target.unlink()
        raise
    return True


class MemoryStore:
    def __init__(self, root: Path, _config: MemoryFilesConfig):
        self.root = root.expanduser().resolve()
        self.lock_path = self.root / ".keepygaga.lock"
        self.lock = FileLock(str(self.lock_path), timeout=30)

    def list_files(self) -> dict[str, object]:
        return self._run_locked(self._list_locked)

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

    def _run_locked(self, callback: Callable[[], dict[str, object]]) -> dict[str, object]:
        if not self.root.is_dir():
            return {
                "status": "not_initialized",
                "message": f"memory root does not exist: {self.root}",
            }
        if self.lock_path.is_symlink():
            return {
                "status": "invalid_source",
                "message": f"memory lock path must not be a symlink: {self.lock_path}",
            }
        try:
            with self.lock:
                return callback()
        except Timeout:
            return {
                "status": "write_conflict",
                "message": "could not acquire the global memory lock",
            }
        except MemoryValidationError as exc:
            return exc.response()
        except Exception as exc:
            return {
                "status": "write_conflict",
                "message": f"{type(exc).__name__}: {exc}",
            }

    def _catalog_paths(self) -> list[str]:
        missing: list[str] = []
        paths: list[str] = []
        for directory_name in DYNAMIC_DIRS:
            directory = self.root / directory_name
            if directory.is_symlink():
                raise MemoryValidationError(
                    "invalid_source", f"memory directory must not be a symlink: {directory}"
                )
            if not directory.is_dir():
                missing.append(str(directory))
        for relative in FIXED_PATHS:
            target = self.root / relative
            if target.is_symlink():
                raise MemoryValidationError(
                    "invalid_source", f"memory path must not be a symlink: {target}"
                )
            if target.is_file():
                paths.append(relative)
            else:
                missing.append(str(target))
        for directory_name in DYNAMIC_DIRS:
            directory = self.root / directory_name
            if not directory.is_dir():
                continue
            for target in sorted(directory.iterdir(), key=lambda item: item.name):
                if target.suffix != ".md":
                    continue
                if target.is_symlink() or not target.is_file():
                    raise MemoryValidationError(
                        "invalid_source", f"memory path must be a regular file: {target}"
                    )
                paths.append(f"{directory_name}/{target.name}")
        if missing:
            raise MemoryValidationError(
                "not_initialized",
                "memory tree is not initialized: " + ", ".join(missing),
            )
        return paths

    def _load_catalog(self) -> dict[str, LoadedFile]:
        files: dict[str, LoadedFile] = {}
        for relative in self._catalog_paths():
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

    @staticmethod
    def _read_catalog_text(target: Path, relative: str) -> str:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target, flags)
        except OSError as exc:
            if exc.errno == errno.ELOOP or target.is_symlink():
                raise MemoryValidationError(
                    "invalid_source",
                    f"memory path must not be a symlink: {target}",
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
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _list_locked(self) -> dict[str, object]:
        files = self._load_catalog()
        listing: list[dict[str, object]] = []
        for path, loaded in files.items():
            item: dict[str, object] = {
                "path": path,
                "description": loaded.document.description,
            }
            if loaded.document.aliases:
                item["aliases"] = list(loaded.document.aliases)
            listing.append(item)
        return {"status": "ok", "files": listing}

    def _read_locked(self, paths: list[str]) -> dict[str, object]:
        if not paths or len(paths) > MAX_READ_PATHS:
            raise MemoryValidationError(
                "invalid_entry", f"paths must contain between 1 and {MAX_READ_PATHS} paths"
            )
        canonical = [canonical_memory_path(path) for path in paths]
        if len(canonical) != len(set(canonical)):
            raise MemoryValidationError("invalid_entry", "paths must not contain duplicates")
        files = self._load_catalog()
        return {
            "status": "ok",
            "files": [self._read_item(self._require_existing(files, path)) for path in canonical],
        }

    def _inspect_locked(self) -> dict[str, object]:
        files = self._load_catalog()
        capacities = {
            str(self.root / path): {
                "used": unicode_chars(loaded.text),
                "soft_limit": soft_limit(path),
                "split_recommended": unicode_chars(loaded.text) > soft_limit(path),
            }
            for path, loaded in files.items()
        }
        return {
            "status": "ok",
            "capacities": capacities,
            "split_recommended": any(
                bool(item["split_recommended"]) for item in capacities.values()
            ),
        }

    def _create_locked(self, operations: list[CreateOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
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
                facts=tuple(operation.facts),
            )
            working[path] = self._loaded(path, document)
            mutations.append(
                self._mutation(
                    "create", "page", path, [fact.content for fact in document.facts]
                )
            )
        return self._finish(initial, working, mutations)

    def _add_locked(self, operations: list[AddOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            document = MemoryDocument(
                name=current.document.name,
                description=current.document.description,
                aliases=current.document.aliases,
                facts=(*current.document.facts, *operation.facts),
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
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
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
                contents = [
                    value
                    for value in (operation.description, *(operation.aliases or []))
                    if value
                ]
                target = "page"
            else:
                if operation.old_fact.basis == "stated" and operation.new_fact.basis != "stated":
                    raise MemoryValidationError(
                        "invalid_entry", "stated facts cannot be downgraded to observed"
                    )
                facts = list(current.document.facts)
                try:
                    index = next(
                        index
                        for index, fact in enumerate(facts)
                        if _fact_key(fact) == _fact_key(operation.old_fact)
                    )
                except StopIteration as exc:
                    raise MemoryValidationError(
                        "not_found", f"fact not found in {current.path}", path=current.path
                    ) from exc
                facts[index] = operation.new_fact
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

    def _move_locked(self, operations: list[MoveOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        for operation in operations:
            source = self._check_version(working, operation.source_path, operation.source_version)
            destination = self._check_version(
                working, operation.destination_path, operation.destination_version
            )
            if source.path == destination.path:
                raise MemoryValidationError("invalid_entry", "source and destination must differ")
            source_facts = list(source.document.facts)
            try:
                index = next(
                    index
                    for index, fact in enumerate(source_facts)
                    if _fact_key(fact) == _fact_key(operation.fact)
                )
            except StopIteration as exc:
                raise MemoryValidationError(
                    "not_found", f"fact not found in {source.path}", path=source.path
                ) from exc
            source_facts.pop(index)
            working[source.path] = self._loaded(
                source.path,
                MemoryDocument(
                    name=source.document.name,
                    description=source.document.description,
                    aliases=source.document.aliases,
                    facts=tuple(source_facts),
                ),
            )
            working[destination.path] = self._loaded(
                destination.path,
                MemoryDocument(
                    name=destination.document.name,
                    description=destination.document.description,
                    aliases=destination.document.aliases,
                    facts=(*destination.document.facts, operation.fact),
                ),
            )
            mutations.append(
                self._mutation(
                    "move",
                    f"{source.path} -> {destination.path}",
                    source.path,
                    [operation.fact.content],
                )
            )
        return self._finish(initial, working, mutations)

    def _rename_locked(self, operations: list[RenameOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
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
                raise MemoryValidationError("already_exists", f"page exists: {new_path}")
            new_name = PurePosixPath(new_path).stem
            aliases = [
                alias
                for alias in current.document.aliases
                if _identity(alias) != _identity(new_name)
            ]
            if _identity(current.document.name) not in {_identity(alias) for alias in aliases}:
                aliases.append(current.document.name)
            document = MemoryDocument(
                name=new_name,
                description=current.document.description,
                aliases=tuple(aliases),
                facts=current.document.facts,
            )
            del working[current.path]
            working[new_path] = self._loaded(new_path, document)
            mutations.append(self._mutation("rename", "page", current.path, [new_path]))
        return self._finish(initial, working, mutations)

    def _delete_locked(self, operations: list[DeleteOperation]) -> dict[str, object]:
        self._require_operations(operations)
        initial = self._load_catalog()
        working = dict(initial)
        mutations: list[dict[str, object]] = []
        for operation in operations:
            current = self._check_version(working, operation.path, operation.if_version)
            if isinstance(operation, DeletePageOperation):
                if not is_dynamic_path(current.path):
                    raise MemoryValidationError(
                        "invalid_path", "only dynamic pages may be deleted", path=current.path
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
                        if _fact_key(fact) == _fact_key(operation.fact)
                    )
                except StopIteration as exc:
                    raise MemoryValidationError(
                        "not_found", f"fact not found in {current.path}", path=current.path
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
    ) -> dict[str, object]:
        _validate_catalog(working)
        changed_paths = sorted(
            path
            for path in set(initial) | set(working)
            if path not in initial
            or path not in working
            or initial[path].text != working[path].text
        )
        if not changed_paths:
            raise MemoryValidationError("invalid_entry", "mutation would not change memory")
        self._commit(initial, working, changed_paths)
        return {
            "status": "applied",
            "mutations": mutations,
            "files": [self._read_item(working[path]) for path in changed_paths if path in working],
        }

    def _commit(
        self,
        initial: dict[str, LoadedFile],
        working: dict[str, LoadedFile],
        changed_paths: list[str],
    ) -> None:
        staged: dict[str, Path] = {}
        applied_paths: list[str] = []
        try:
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
            self._verify_live_versions(initial, changed_paths)
            try:
                for relative in sorted(
                    changed_paths,
                    key=lambda path: self._commit_priority(
                        initial.get(path), working.get(path), path
                    ),
                ):
                    self._verify_live_versions(initial, [relative])
                    target = self.root / relative
                    if relative not in working:
                        target.unlink()
                    else:
                        temporary = staged[relative]
                        if relative in initial:
                            mode = target.stat(follow_symlinks=False).st_mode & 0o7777
                            os.chmod(temporary, mode)
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
                if target.exists() or target.is_symlink():
                    raise MemoryValidationError(
                        "write_conflict", f"memory path appeared during mutation: {relative}"
                    )
                continue
            try:
                text = normalize_text(self._read_catalog_text(target, relative))
            except FileNotFoundError as exc:
                raise MemoryValidationError(
                    "write_conflict", f"memory path disappeared during mutation: {relative}"
                ) from exc
            if sha256_text(text) != before.version:
                raise MemoryValidationError(
                    "write_conflict", f"memory file changed during mutation: {relative}"
                )

    def _assert_parent_safe(self, relative: str) -> None:
        canonical = canonical_memory_path(relative)
        parent = (self.root / canonical).parent
        if parent.is_symlink() or not parent.is_dir():
            raise MemoryValidationError(
                "write_conflict",
                f"memory parent directory is unsafe: {parent}",
                path=canonical,
            )

    def _loaded(self, path: str, document: MemoryDocument) -> LoadedFile:
        text = render_memory_file(document, path)
        return LoadedFile(
            path=path,
            document=_validate_document(document, path),
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
        if unicode_chars(loaded.text) > soft_limit(loaded.path):
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

    @staticmethod
    def _require_operations(operations: Sequence[object]) -> None:
        if not operations or len(operations) > MAX_MUTATION_OPERATIONS:
            raise MemoryValidationError(
                "invalid_entry",
                f"operations must contain between 1 and {MAX_MUTATION_OPERATIONS} operations",
            )

    @staticmethod
    def _mutation(
        action: str, target: str, path: str, contents: Sequence[str]
    ) -> dict[str, object]:
        return {
            "action": action,
            "target": target,
            "path": path,
            "receipt": _receipt(action, path, contents),
        }


def _validate_catalog(files: dict[str, LoadedFile]) -> None:
    identities: dict[str, tuple[str, str]] = {}
    for path, loaded in files.items():
        canonical_memory_path(path)
        document = _validate_document(loaded.document, path)
        for kind, value in (
            ("name", document.name),
            *(("alias", alias) for alias in document.aliases),
        ):
            identity = _identity(value)
            previous = identities.get(identity)
            if previous is not None:
                previous_path, previous_kind = previous
                raise MemoryValidationError(
                    "invalid_entry",
                    f"{kind} {value!r} in {path} conflicts with "
                    f"{previous_kind} in {previous_path}",
                    path=path,
                )
            identities[identity] = (path, kind)
