from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import PurePosixPath
from typing import Any, Literal, cast

import frontmatter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from keepygaga.errors import MemoryValidationError
from keepygaga.paths import canonical_memory_path

MAX_FACT_CONTENT_CHARS = 800
MAX_STORED_FACT_CONTENT_CHARS = 4096
FACT_LINE_RE = re.compile(
    r"^- \[(stated|observed)\] (.+?)(?: \[(\d{4}-\d{2}-\d{2})\])?$"
)
FRONTMATTER_KEY_RE = re.compile(r"^(name|description|sources|aliases):")
FRONTMATTER_FENCE_RE = re.compile(r"^-{3,}\s*$")

Basis = Literal["stated", "observed"]


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def unicode_chars(text: str) -> int:
    return len(normalize_text(text))


def sha256_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactSelector(StrictModel):
    basis: Basis = Field(
        description=(
            "Evidence basis: stated for the user's explicit statement; observed for "
            "Agent derivation or inference from current visible material."
        )
    )
    content: str = Field(
        max_length=MAX_STORED_FACT_CONTENT_CHARS,
        description="Exact basis and content copied from an existing Page Snapshot.",
    )

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, value: object) -> object:
        return _normalized_fact_content(value)


class Fact(FactSelector):
    basis: Basis = Field(
        description=(
            "Evidence basis: stated for the user's explicit statement; observed for "
            "Agent derivation or inference from current visible material."
        )
    )
    content: str = Field(
        max_length=MAX_FACT_CONTENT_CHARS,
        description="One complete, independently maintainable, single-line assertion.",
    )


class StoredFact(FactSelector):
    date: str | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = calendar_date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "fact date must be a valid YYYY-MM-DD calendar date"
            ) from exc
        if parsed.isoformat() != value:
            raise ValueError("fact date must use YYYY-MM-DD")
        return value


@dataclass(frozen=True)
class MemoryDocument:
    name: str
    description: str
    aliases: tuple[str, ...]
    facts: tuple[StoredFact, ...]


def _identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _one_line(value: str, field: str) -> str:
    normalized = normalize_text(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if "\x00" in normalized or "\n" in normalized:
        raise ValueError(f"{field} must be one non-empty line")
    return normalized


def _normalized_fact_content(value: object) -> object:
    if not isinstance(value, str):
        return value
    return _one_line(value, "fact content")


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


def fact_key(fact: FactSelector) -> tuple[str, str]:
    return fact.basis, fact.content


def stored_fact(fact: Fact | StoredFact, *, date: str | None = None) -> StoredFact:
    return StoredFact(
        basis=fact.basis,
        content=fact.content,
        date=fact.date if isinstance(fact, StoredFact) and date is None else date,
    )


def receipt(action: str, scope: str, contents: Sequence[str]) -> str:
    prefix = f"🧠 {action} [{scope}]"
    text = f"{prefix}: {' · '.join(contents)}" if contents else prefix
    backtick_runs = re.findall(r"`+", text)
    fence = "`" * (max((len(run) for run in backtick_runs), default=0) + 1)
    padding = " " if text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def parse_page_metadata(text: str, path: str) -> MemoryDocument:
    canonical_memory_path(path)
    metadata, body = _parse_frontmatter(normalize_text(text), path, include_body=False)
    _assert_fact_body(body, path)
    aliases = _string_array(metadata["aliases"], "aliases", maximum=8)
    return validate_page_metadata(
        MemoryDocument(
            name=metadata["name"],
            description=metadata["description"],
            aliases=aliases,
            facts=(),
        ),
        path,
    )


def validate_page_metadata(document: MemoryDocument, path: str) -> MemoryDocument:
    return MemoryDocument(
        name=_validated_name(document.name, path),
        description=_validated_description(document.description, path),
        aliases=_validated_aliases(document.aliases, path),
        facts=document.facts,
    )


def validate_document(document: MemoryDocument, path: str) -> MemoryDocument:
    metadata = validate_page_metadata(document, path)
    facts = tuple(stored_fact(fact) for fact in document.facts)
    fact_keys = [fact_key(fact) for fact in facts]
    if len(fact_keys) != len(set(fact_keys)):
        raise MemoryValidationError(
            "invalid_entry", f"{path} contains duplicate facts", path=path
        )
    return MemoryDocument(
        name=metadata.name,
        description=metadata.description,
        aliases=metadata.aliases,
        facts=facts,
    )


def _validated_name(name: str, path: str) -> str:
    expected_name = PurePosixPath(path).stem
    try:
        normalized = _one_line(name, "name")
    except ValueError as orig_exc:
        raise MemoryValidationError(
            "invalid_entry", str(orig_exc), path=path
        ) from orig_exc
    if normalized != expected_name:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter name must equal file stem {expected_name!r}",
            path=path,
        )
    return normalized


def _validated_description(description: str, path: str) -> str:
    try:
        return _one_line(description, "description")
    except ValueError as orig_exc:
        raise MemoryValidationError(
            "invalid_entry", str(orig_exc), path=path
        ) from orig_exc


def _validated_aliases(aliases: tuple[str, ...], path: str) -> tuple[str, ...]:
    expected_name = PurePosixPath(path).stem
    normalized = _string_array(list(aliases), "aliases", maximum=8)
    if _identity(expected_name) in {_identity(alias) for alias in normalized}:
        raise MemoryValidationError(
            "invalid_entry", f"{path} aliases cannot repeat its name", path=path
        )
    return normalized


def _assert_fact_body(body_text: str, path: str) -> None:
    body = normalize_text(body_text).strip()
    if not body:
        return
    seen: set[tuple[str, str]] = set()
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
        raw_content = match.group(2)
        raw_date = match.group(3)
        try:
            fact = StoredFact(
                basis=cast(Basis, basis), content=raw_content, date=raw_date
            )
        except ValueError as orig_exc:
            raise MemoryValidationError(
                "invalid_source",
                f"{path} contains a fact that violates the page schema",
                path=path,
            ) from orig_exc
        key = fact_key(fact)
        if key in seen:
            raise MemoryValidationError(
                "invalid_entry", f"{path} contains duplicate facts", path=path
            )
        seen.add(key)


def _parse_frontmatter(
    normalized: str, path: str, *, include_body: bool = True
) -> tuple[dict[str, Any], str]:
    if not normalized.startswith("---\n"):
        raise MemoryValidationError(
            "invalid_source", f"{path} must begin with YAML frontmatter", path=path
        )
    lines = normalized.split("\n")
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if FRONTMATTER_FENCE_RE.fullmatch(line)
        ),
        None,
    )
    if closing_index is None:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must end with a --- delimiter",
            path=path,
        )
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
    header = "\n".join(lines[: closing_index + 1]) + "\n"
    try:
        post = frontmatter.loads(header if not include_body else normalized)
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
    if include_body:
        return metadata, post.content
    body = "\n".join(lines[closing_index + 1 :])
    if body:
        body += "\n"
    return metadata, body


def _parse_facts(body_text: str, path: str) -> tuple[StoredFact, ...]:
    _assert_fact_body(body_text, path)
    facts: list[StoredFact] = []
    body = normalize_text(body_text).strip()
    if not body:
        return ()
    for line in body.splitlines():
        if not line.strip():
            continue
        match = FACT_LINE_RE.fullmatch(line)
        assert match is not None
        basis = match.group(1)
        assert basis in ("stated", "observed")
        try:
            facts.append(
                StoredFact(
                    basis=cast(Basis, basis),
                    content=match.group(2),
                    date=match.group(3),
                )
            )
        except ValueError as orig_exc:
            raise MemoryValidationError(
                "invalid_source",
                f"{path} contains a fact that violates the page schema",
                path=path,
            ) from orig_exc
    return tuple(facts)


def parse_memory_file(text: str, path: str) -> MemoryDocument:
    canonical_memory_path(path)
    metadata, body = _parse_frontmatter(normalize_text(text), path)
    aliases = _string_array(metadata["aliases"], "aliases", maximum=8)
    return validate_document(
        MemoryDocument(
            name=metadata["name"],
            description=metadata["description"],
            aliases=aliases,
            facts=_parse_facts(body, path),
        ),
        path,
    )


def _repair_frontmatter(normalized: str, path: str) -> tuple[dict[str, Any], list[str]]:
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        raise MemoryValidationError(
            "invalid_source", f"{path} must begin with YAML frontmatter", path=path
        )
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must end with a --- delimiter",
            path=path,
        )
    header_lines = lines[1:closing_index]
    field_names = [
        match.group(1)
        for line in header_lines
        if (match := FRONTMATTER_KEY_RE.match(line.strip())) is not None
    ]
    if len(field_names) != len(set(field_names)):
        raise MemoryValidationError(
            "invalid_source", f"{path} contains duplicate frontmatter fields", path=path
        )
    header = "---\n" + "\n".join(header_lines) + "\n---\n"
    try:
        metadata = dict(frontmatter.loads(header).metadata)
    except Exception as exc:
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter could not be parsed: {type(exc).__name__}: {exc}",
            path=path,
        ) from exc
    keys = set(metadata)
    if not {"name", "description", "aliases"}.issubset(keys) or not keys.issubset(
        {"name", "description", "sources", "aliases"}
    ):
        raise MemoryValidationError(
            "invalid_source",
            f"{path} frontmatter must contain name, description, aliases",
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
    return metadata, lines[closing_index + 1 :]


def _repair_aliases(value: object, path: str) -> tuple[str, ...]:
    raw_aliases = value
    if not isinstance(raw_aliases, list) or not all(
        isinstance(alias, str) for alias in raw_aliases
    ):
        raise MemoryValidationError(
            "invalid_source", "aliases must be a string array", path=path
        )
    try:
        aliases = tuple(_one_line(alias, "aliases") for alias in raw_aliases)
    except ValueError as exc:
        raise MemoryValidationError("invalid_entry", str(exc), path=path) from exc
    name_identity = _identity(PurePosixPath(path).stem)
    repaired_aliases: list[str] = []
    seen_aliases: set[str] = set()
    for alias in aliases:
        identity = _identity(alias)
        if identity == name_identity or identity in seen_aliases:
            continue
        seen_aliases.add(identity)
        repaired_aliases.append(alias)
    if len(repaired_aliases) > 8:
        raise MemoryValidationError(
            "invalid_entry", "aliases cannot contain more than 8 values", path=path
        )

    return tuple(repaired_aliases)


def _repair_facts(lines: Sequence[str], path: str) -> tuple[StoredFact, ...]:
    facts: list[StoredFact] = []
    seen_facts: dict[tuple[str, str], StoredFact] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        match = FACT_LINE_RE.fullmatch(line)
        if match is None:
            raise MemoryValidationError(
                "invalid_source",
                f"{path} body may contain only - [stated]/[observed] bullets",
                path=path,
            )
        try:
            basis = match.group(1)
            assert basis in ("stated", "observed")
            fact = StoredFact(
                basis=cast(Basis, basis),
                content=match.group(2),
                date=match.group(3),
            )
        except ValueError as exc:
            raise MemoryValidationError(
                "invalid_source",
                f"{path} contains a fact that violates the page schema",
                path=path,
            ) from exc
        key = fact_key(fact)
        previous = seen_facts.get(key)
        if previous is not None:
            if previous != fact:
                raise MemoryValidationError(
                    "invalid_entry",
                    f"{path} contains conflicting duplicate facts",
                    path=path,
                )
            continue
        seen_facts[key] = fact
        facts.append(fact)
    return tuple(facts)


def repair_memory_file(text: str, path: str) -> MemoryDocument:
    """Return the sole canonical document for mechanically repairable text."""
    canonical_memory_path(path)
    metadata, body_lines = _repair_frontmatter(normalize_text(text), path)

    return validate_document(
        MemoryDocument(
            name=metadata["name"],
            description=metadata["description"],
            aliases=_repair_aliases(metadata["aliases"], path),
            facts=_repair_facts(body_lines, path),
        ),
        path,
    )


def render_memory_file(document: MemoryDocument, path: str) -> str:
    validated = validate_document(document, path)
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
        lines.extend(
            f"- [{fact.basis}] {fact.content}"
            + (f" [{fact.date}]" if fact.date is not None else "")
            for fact in validated.facts
        )
    return "\n".join(lines).rstrip() + "\n"
