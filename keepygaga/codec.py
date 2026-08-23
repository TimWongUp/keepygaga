from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

import frontmatter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from keepygaga.errors import MemoryValidationError
from keepygaga.paths import canonical_memory_path

MAX_FACT_CONTENT_CHARS = 4096
PROFILE_FACT_CONTENT_LIMIT = 300
FACT_LINE_RE = re.compile(r"^- \[(stated|observed)\] (.+)$")
FRONTMATTER_KEY_RE = re.compile(r"^(name|description|sources|aliases):")

Basis = Literal["stated", "observed"]


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def unicode_chars(text: str) -> int:
    return len(normalize_text(text))


def sha256_text(text: str) -> str:
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(StrictModel):
    basis: Basis = Field(
        description=(
            "Evidence basis: stated for the user's explicit statement; observed only "
            "where the Agent Contract permits a repeated behavioral observation."
        )
    )
    content: str = Field(
        max_length=MAX_FACT_CONTENT_CHARS,
        description="One complete, independently maintainable, single-line assertion.",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = normalize_text(value).strip()
        if not normalized:
            raise ValueError("fact content must not be empty")
        if "\x00" in normalized or "\n" in normalized:
            raise ValueError("fact content must be one non-empty line")
        return normalized


@dataclass(frozen=True)
class MemoryDocument:
    name: str
    description: str
    aliases: tuple[str, ...]
    facts: tuple[Fact, ...]


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


def fact_key(fact: Fact) -> tuple[str, str]:
    return fact.basis, fact.content


def receipt(action: str, scope: str, contents: Sequence[str]) -> str:
    prefix = f"🧠 {action} [{scope}]"
    text = f"{prefix}: {' · '.join(contents)}" if contents else prefix
    backtick_runs = re.findall(r"`+", text)
    fence = "`" * (max((len(run) for run in backtick_runs), default=0) + 1)
    padding = " " if text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def validate_document(document: MemoryDocument, path: str) -> MemoryDocument:
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
    fact_keys = [fact_key(fact) for fact in facts]
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
            try:
                facts.append(Fact(basis=basis, content=match.group(2)))
            except ValueError as exc:
                raise MemoryValidationError(
                    "invalid_source",
                    f"{path} contains a fact that violates the page schema",
                    path=path,
                ) from exc
    return validate_document(
        MemoryDocument(
            name=metadata["name"],
            description=metadata["description"],
            aliases=aliases,
            facts=tuple(facts),
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
        lines.extend(f"- [{fact.basis}] {fact.content}" for fact in validated.facts)
    return "\n".join(lines).rstrip() + "\n"
