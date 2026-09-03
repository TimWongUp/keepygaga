from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from keepygaga.codec import (
    Fact,
    FactSelector,
    StrictModel,
    _one_line,
    fact_key,
    unicode_chars,
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

DEFAULT_DESCRIPTIONS = {
    "profile.md": "用户明确陈述的稳定身份、背景与长期角色。",
    "preferences.md": "用户希望 Agent 长期遵循的回应方式、工作偏好与条件检索偏好。",
}

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
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Replacement page description to apply with the Fact addition.",
    )
    facts: list[Fact] = Field(
        min_length=1,
        max_length=MAX_FACTS_PER_OPERATION,
        description="Facts to append; Store validation rejects exact duplicates only.",
    )

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        return _agent_description(value) if value is not None else None


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
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Replacement page description to apply with the Fact update.",
    )

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        return _agent_description(value) if value is not None else None

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
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description=(
            "Replacement description for an existing destination or required initial "
            "description for a new destination."
        ),
    )
    aliases: list[str] | None = Field(
        default=None,
        max_length=MAX_ALIASES_PER_PAGE,
        description=(
            "Required initial aliases for a new destination; omit for an existing "
            "destination and update them separately with target=page."
        ),
    )
    source_description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Replacement source page description to apply with the Fact move.",
    )
    facts: list[FactSelector] = Field(
        min_length=1,
        max_length=MAX_FACTS_PER_OPERATION,
        description=(
            "All exact Facts to move between this source/destination pair in one "
            "operation; copy them unchanged from the latest source Page Snapshot."
        ),
    )

    @field_validator("description", "source_description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        return _agent_description(value) if value is not None else None

    @model_validator(mode="after")
    def validate_destination(self) -> MoveOperation:
        existing = (
            self.destination_path is not None or self.destination_version is not None
        )
        new = self.new_path is not None
        if existing == new:
            raise ValueError(
                "move requires exactly one existing or new destination mode"
            )
        if existing and (
            self.destination_path is None or self.destination_version is None
        ):
            raise ValueError("existing destination requires path and version")
        if existing and self.aliases is not None:
            raise ValueError(
                "existing destination aliases must be updated with target=page"
            )
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
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Replacement page description to apply with the Fact deletion.",
    )
    authorization: Literal["user_requested"] = Field(
        description=(
            "Audit assertion; set only after explicit current-turn user authorization."
        )
    )

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: object) -> str | None:
        return _agent_description(value) if value is not None else None


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


def page_limit(path: str) -> int:
    if path == "profile.md":
        return PROFILE_PAGE_LIMIT
    if path == "preferences.md":
        return PREFERENCES_PAGE_LIMIT
    return DYNAMIC_PAGE_LIMIT
