from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from keepygaga import codec, memory_files, memory_init, paths
from keepygaga import memory as memory_module
from keepygaga import memory_store as memory_store_module
from keepygaga.config import MemoryFilesConfig, MemoryLimitsConfig
from keepygaga.memory import (
    AddOperation,
    CreateOperation,
    DeleteFactOperation,
    DeletePageOperation,
    Fact,
    FactSelector,
    MemoryDocument,
    MemoryStore,
    MoveOperation,
    RenameOperation,
    RepairPageOperation,
    StoredFact,
    UpdateFactOperation,
    UpdatePageOperation,
    initialize_memory_tree,
    parse_memory_file,
    render_memory_file,
)

CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "core-memory-v1"


def test_memory_module_reexports_canonical_models_and_paths() -> None:
    assert memory_module.Basis is codec.Basis
    assert memory_module.Fact is codec.Fact
    assert memory_module.FactSelector is codec.FactSelector
    assert memory_module.MemoryDocument is codec.MemoryDocument
    assert memory_module.StoredFact is codec.StoredFact
    assert memory_module.MAX_FACT_CONTENT_CHARS == codec.MAX_FACT_CONTENT_CHARS
    assert memory_module.FACT_LINE_RE is codec.FACT_LINE_RE
    assert memory_module.FRONTMATTER_KEY_RE is codec.FRONTMATTER_KEY_RE
    assert memory_module.DYNAMIC_STEM_RE is paths.DYNAMIC_STEM_RE
    assert memory_module.canonical_memory_path is paths.canonical_memory_path
    assert memory_module.canonical_path is paths.canonical_path


@pytest.fixture
def memory_store(tmp_path: Path) -> tuple[Path, MemoryStore]:
    root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(root))
    assert initialize_memory_tree(root, config)["status"] == "applied"
    return root, MemoryStore(root, config)


def fact(content: str, basis: str = "stated") -> Fact:
    return Fact(basis=basis, content=content)  # type: ignore[arg-type]


def selector(content: str, basis: str = "stated") -> FactSelector:
    return FactSelector(basis=basis, content=content)  # type: ignore[arg-type]


def test_core_memory_v1_contract_matches_current_page_format() -> None:
    documents = {
        "profile.md": MemoryDocument(
            name="profile",
            description="用户明确陈述的稳定身份、背景与长期角色。",
            aliases=("identity",),
            facts=(
                StoredFact(
                    basis="stated",
                    content="Contract profile fact.",
                    date="2026-09-02",
                ),
            ),
        ),
        "preferences.md": MemoryDocument(
            name="preferences",
            description="用户希望所有接入 Agent 跨任务长期遵循的回应、工作与条件检索偏好。",
            aliases=("working-style",),
            facts=(
                StoredFact(
                    basis="stated",
                    content="Contract preference fact.",
                    date="2026-09-02",
                ),
            ),
        ),
    }
    for path, document in documents.items():
        canonical = (CONTRACT_ROOT / "canonical" / path).read_text(encoding="utf-8")
        legacy = (CONTRACT_ROOT / "legacy-sources" / path).read_text(encoding="utf-8")
        assert canonical == render_memory_file(document, path)
        assert parse_memory_file(canonical, path) == document
        legacy_document = parse_memory_file(legacy, path)
        assert (
            legacy_document.name,
            legacy_document.description,
            legacy_document.aliases,
        ) == (document.name, document.description, document.aliases)
        assert [fact.date for fact in legacy_document.facts] == [None]
        assert [fact.content for fact in legacy_document.facts] == [
            fact.content for fact in document.facts
        ]

    manifest = json.loads((CONTRACT_ROOT / "contract.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["page_version"] == {
        "normalization": "crlf-and-cr-to-lf",
        "encoding": "utf-8",
        "algorithm": "sha256",
        "prefix": "sha256:",
    }
    assert manifest["fact_normalization"] == {
        "line_pattern": codec.FACT_LINE_RE.pattern,
        "blank_lines": "ignored",
        "content_trim": "unicode-strip",
        "max_write_content_chars": codec.MAX_FACT_CONTENT_CHARS,
        "max_selector_content_chars": codec.MAX_STORED_FACT_CONTENT_CHARS,
        "max_read_content_chars": codec.MAX_STORED_FACT_CONTENT_CHARS,
        "length_checked": "after-trim",
        "duplicate_key": ["basis", "trimmed-content"],
        "date_suffix": " [YYYY-MM-DD]",
        "legacy_date": None,
    }
    assert manifest["limits"] == {
        "max_dynamic_pages": memory_module.DYNAMIC_PAGE_LIMITS,
        "max_description_chars": memory_module.MAX_DESCRIPTION_CHARS,
        "max_aliases_per_page": memory_module.MAX_ALIASES_PER_PAGE,
        "max_fixed_page_chars": memory_module.PROFILE_PAGE_LIMIT,
        "max_dynamic_page_chars": memory_module.DYNAMIC_PAGE_LIMIT,
        "max_read_paths": memory_module.MAX_READ_PATHS,
        "max_mutation_operations": memory_module.MAX_MUTATION_OPERATIONS,
        "max_facts_per_operation": memory_module.MAX_FACTS_PER_OPERATION,
    }
    assert Fact(basis="stated", content="  padded  ").content == "padded"
    assert len(Fact(basis="stated", content="  " + "x" * 800).content) == 800
    with pytest.raises(ValidationError):
        Fact(basis="stated", content="x" * (codec.MAX_FACT_CONTENT_CHARS + 1))
    assert manifest["fixtures"] == {
        relative: codec.sha256_text(
            codec.normalize_text((CONTRACT_ROOT / relative).read_text(encoding="utf-8"))
        )
        for relative in (
            "canonical/profile.md",
            "canonical/preferences.md",
            "legacy-sources/profile.md",
            "legacy-sources/preferences.md",
        )
    }


def create(
    path: str, content: str, aliases: list[str] | None = None
) -> CreateOperation:
    return CreateOperation(
        path=path,
        description=f"Route {path}.",
        aliases=aliases or [],
        facts=[fact(content)],
    )


def read_file(store: MemoryStore, path: str) -> dict[str, object]:
    result = store.read([path])
    assert result["status"] == "ok"
    files = result["files"]
    assert isinstance(files, list)
    item = files[0]
    assert isinstance(item, dict)
    return item


def version(store: MemoryStore, path: str) -> str:
    value = read_file(store, path)["version"]
    assert isinstance(value, str)
    return value


def test_fact_is_one_nonempty_line() -> None:
    assert fact("  complete assertion  ").content == "complete assertion"
    with pytest.raises(ValidationError):
        fact("")
    with pytest.raises(ValidationError):
        fact("two\nlines")


def test_initialize_creates_minimal_tree(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, _ = memory_store
    files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.md")
        if path.is_file()
    }
    assert files == {"profile.md", "preferences.md"}
    assert {path.name for path in root.iterdir() if path.is_dir()} == {
        "topics",
        "areas",
        "people",
    }
    profile_text = (root / "profile.md").read_text(encoding="utf-8")
    preferences_text = (root / "preferences.md").read_text(encoding="utf-8")
    assert "sources:" not in profile_text
    profile = parse_memory_file(profile_text, "profile.md")
    preferences = parse_memory_file(preferences_text, "preferences.md")
    assert profile.name == "profile"
    assert profile.description == "用户明确陈述的稳定身份、背景与长期角色。"
    assert (
        preferences.description
        == "用户希望所有接入 Agent 跨任务长期遵循的回应、工作与条件检索偏好。"
    )


def test_initialize_returns_optional_onboarding_for_created_pages(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(root))

    first = initialize_memory_tree(root, config)
    second = initialize_memory_tree(root, config)

    assert first["onboarding"] == {
        "optional": True,
        "created_pages": ["profile.md", "preferences.md"],
    }
    assert second["status"] == "no_op"
    assert "onboarding" not in second


def test_initialize_directory_only_repair_is_applied_without_onboarding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(root))
    assert initialize_memory_tree(root, config)["status"] == "applied"
    for directory in ("topics", "areas", "people"):
        (root / directory).rmdir()

    result = initialize_memory_tree(root, config)

    assert result["status"] == "applied"
    assert result["files"] == []
    assert result["directories"] == [
        str(root / "topics"),
        str(root / "areas"),
        str(root / "people"),
    ]
    assert "onboarding" not in result


def test_initialize_never_overwrites_an_existing_page(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    profile = root / "profile.md"
    human_content = render_memory_file(
        MemoryDocument(
            name="profile",
            description="Human-managed profile.",
            aliases=(),
            facts=(StoredFact(basis="stated", content="Human content."),),
        ),
        "profile.md",
    )
    profile.write_text(human_content, encoding="utf-8")
    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))
    assert result["status"] == "applied"
    assert result["onboarding"] == {
        "optional": True,
        "created_pages": ["preferences.md"],
    }
    assert profile.read_text(encoding="utf-8") == human_content


def test_initialize_rejects_non_file_fixed_page(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "profile.md").mkdir()

    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))

    assert result["status"] == "invalid_source"
    assert "regular file" in str(result["message"])
    assert "onboarding" not in result


def test_initialize_reports_created_directories_on_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    original_mkdir = memory_files._mkdir_new

    def fail_areas(path: Path, *args, **kwargs) -> None:
        if path == root / "areas":
            raise PermissionError("simulated directory failure")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(memory_files, "_mkdir_new", fail_areas)

    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))

    assert result["status"] == "partial_commit"
    assert result["files"] == []
    assert result["directories"] == [str(root / "topics")]
    assert "onboarding" not in result


def test_initialize_partial_file_commit_does_not_offer_onboarding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "memory"
    original_create = memory_init._exclusive_create

    def fail_preferences(target: Path, text: str) -> bool:
        if target.name == "preferences.md":
            raise PermissionError("simulated page failure")
        return original_create(target, text)

    monkeypatch.setattr(memory_init, "_exclusive_create", fail_preferences)

    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))

    assert result["status"] == "partial_commit"
    assert result["files"] == [str(root / "profile.md")]
    assert "onboarding" not in result


def test_inspect_reports_invalid_utf8_with_exact_path(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    (root / "profile.md").write_bytes(b"\xff")

    result = store.inspect()

    assert result["status"] == "invalid_source"
    assert result["path"] == "profile.md"
    assert "UTF-8" in str(result["message"])


def test_inspect_reports_invalid_fact_with_exact_path(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "preferences.md"
    page.write_text(
        page.read_text(encoding="utf-8") + f"\n- [stated] {'x' * 4097}\n",
        encoding="utf-8",
    )

    result = store.inspect()

    assert result["status"] == "invalid_source"
    assert result["path"] == "preferences.md"
    assert "page schema" in str(result["message"])


def test_legacy_sources_are_read_but_removed_on_write(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "profile.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "aliases: []", 'sources: ["codex"]\naliases: []'
        ),
        encoding="utf-8",
    )
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("Stable fact.")],
            )
        ]
    )
    assert result["status"] == "applied"
    assert "sources:" not in page.read_text(encoding="utf-8")


def test_list_rejects_invalid_body(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    page = root / "topics" / "broken.md"
    page.write_text(
        render_memory_file(
            MemoryDocument(
                name="broken",
                description="Broken page.",
                aliases=(),
                facts=(),
            ),
            "topics/broken.md",
        )
        + "\nnot a fact\n",
        encoding="utf-8",
    )
    result = store.list_files("topics")
    assert result["status"] == "invalid_source"
    assert result["path"] == "topics/broken.md"
    assert result["repairable"] is False
    assert "raw" not in result
    assert "version" not in result
    assert store.list_files("areas") == {"status": "ok", "files": []}


def test_list_rejects_oversized_fact(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    page = root / "topics" / "oversized.md"
    page.write_text(
        "---\nname: oversized\ndescription: oversized\naliases: []\n---\n\n"
        f"- [stated] {chr(120) * 4097}\n",
        encoding="utf-8",
    )
    result = store.list_files("topics")
    assert result["status"] == "invalid_source"
    assert result["path"] == "topics/oversized.md"
    assert result["repairable"] is False
    assert "raw" not in result
    assert "version" not in result


@pytest.mark.parametrize(
    "duplicate_key",
    [
        "description :",
        '"description":',
        "!!str description:",
        '"descriptio\\u006e":',
    ],
)
def test_frontmatter_duplicate_variants_are_rejected(
    memory_store: tuple[Path, MemoryStore],
    duplicate_key: str,
) -> None:
    root, store = memory_store
    page = root / "topics" / "duplicate.md"
    original = (
        "---\n"
        "name: duplicate\n"
        "description: Original.\n"
        f"{duplicate_key} Changed.\n"
        "aliases: []\n"
        "---\n\n"
        "- [stated] Keep.\n"
    )
    page.write_text(original, encoding="utf-8")

    result = store.list_files("topics")

    assert result["status"] == "invalid_source"
    assert result["repairable"] is False
    assert "raw" not in result
    assert page.read_text(encoding="utf-8") == original


def test_list_rejects_padded_frontmatter_fence(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "padded.md"
    nl = chr(10)
    page.write_text(
        "---"
        + nl
        + "name: padded"
        + nl
        + "description: desc"
        + nl
        + "aliases: []"
        + nl
        + "---   "
        + nl
        + "- [stated] x"
        + nl
        + "---"
        + nl,
        encoding="utf-8",
    )
    listed = store.list_files("topics")
    assert listed["status"] == "invalid_source"
    assert listed["path"] == "topics/padded.md"
    other = store.read(["preferences.md"])
    assert other["status"] == "ok"


def test_list_rejects_unicode_line_separator_fence(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "people" / "broken.md"
    nl = chr(10)
    page.write_text(
        "---"
        + nl
        + "name: broken"
        + nl
        + "description: desc"
        + nl
        + "aliases: []"
        + chr(0x2028)
        + "---"
        + nl,
        encoding="utf-8",
    )
    listed = store.list_files("people")
    assert listed["status"] == "invalid_source"
    assert listed["path"] == "people/broken.md"
    other = store.read(["preferences.md"])
    assert other["status"] == "ok"


@pytest.mark.parametrize(
    "separator",
    ["\u0085", "\u2028", "\u2029", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"],
)
def test_agent_fact_write_rejects_all_line_separators(separator: str) -> None:
    with pytest.raises(ValidationError, match="one non-empty line"):
        fact(f"before{separator}after")


def test_list_is_minimal_and_read_is_structured(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert (
        store.create([create("topics/ai.md", "AI fact.", ["人工智能"])])["status"]
        == "applied"
    )
    listed = store.list_files("topics")
    assert listed["status"] == "ok"
    by_path = {item["path"]: item for item in listed["files"]}  # type: ignore[index]
    assert set(by_path["topics/ai.md"]) == {"path", "description", "aliases"}
    assert by_path["topics/ai.md"]["aliases"] == ["人工智能"]
    item = read_file(store, "topics/ai.md")
    assert set(item) == {
        "path",
        "name",
        "description",
        "aliases",
        "facts",
        "version",
    }


def test_read_rejects_invalid_count(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    assert store.read([])["status"] == "invalid_entry"
    assert store.read(["profile.md"] * 16)["status"] == "invalid_entry"


def test_create_add_update_and_page_metadata(
    memory_store: tuple[Path, MemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2032-03-04")
    created = store.create([create("areas/work.md", "First fact.")])
    assert created["status"] == "applied"
    added = store.add(
        [
            AddOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                description="Work with two facts.",
                facts=[fact("Second fact.")],
            )
        ]
    )
    assert added["status"] == "applied"
    assert (
        added["files"][0]["description"] == "Work with two facts."  # type: ignore[index]
    )
    updated = store.update(
        [
            UpdateFactOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                target="fact",
                old_fact=fact("First fact."),
                new_fact=fact("Refined first fact."),
                description="Refined work context.",
            )
        ]
    )
    assert updated["status"] == "applied"
    assert (
        updated["files"][0]["description"] == "Refined work context."  # type: ignore[index]
    )
    metadata = store.update(
        [
            UpdatePageOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                target="page",
                aliases=["工作"],
            )
        ]
    )
    assert metadata["status"] == "applied"
    item = read_file(store, "areas/work.md")
    assert item["description"] == "Refined work context."
    assert item["aliases"] == ["工作"]
    assert item["facts"] == [
        {"basis": "stated", "content": "Refined first fact.", "date": "2032-03-04"},
        {"basis": "stated", "content": "Second fact.", "date": "2032-03-04"},
    ]


def test_stated_fact_cannot_be_downgraded(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.update(
        [
            UpdateFactOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                target="fact",
                old_fact=fact("Missing."),
                new_fact=fact("Observed.", "observed"),
            )
        ]
    )
    assert result["status"] == "invalid_entry"


def test_observed_fact_can_be_promoted_to_stated(
    memory_store: tuple[Path, MemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2032-03-03")
    added = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("Prefers concise answers.", "observed")],
            )
        ]
    )
    assert added["status"] == "applied"

    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2032-03-04")

    result = store.update(
        [
            UpdateFactOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                target="fact",
                old_fact=fact("Prefers concise answers.", "observed"),
                new_fact=fact("Prefers concise answers."),
            )
        ]
    )

    assert result["status"] == "applied"
    assert read_file(store, "preferences.md")["facts"] == [
        {
            "basis": "stated",
            "content": "Prefers concise answers.",
            "date": "2032-03-04",
        }
    ]


def test_batch_preflight_failure_writes_nothing(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    before = (root / "profile.md").read_text(encoding="utf-8")
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("Must not persist.")],
            ),
            AddOperation(
                path="preferences.md",
                if_version="sha256:" + "0" * 64,
                facts=[fact("Also rejected.")],
            ),
        ]
    )
    assert result["status"] == "write_conflict"
    assert (root / "profile.md").read_text(encoding="utf-8") == before


def test_manual_edit_after_read_wins(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    stale = version(store, "profile.md")
    page = root / "profile.md"
    human = page.read_text(encoding="utf-8").rstrip() + "\n- [stated] Human edit.\n"
    page.write_text(human, encoding="utf-8")
    result = store.add(
        [AddOperation(path="profile.md", if_version=stale, facts=[fact("Agent edit.")])]
    )
    assert result["status"] == "write_conflict"
    assert page.read_text(encoding="utf-8") == human


def test_write_conflict_latest_can_be_reused_without_read(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    stale = version(store, "profile.md")
    page = root / "profile.md"
    page.write_text(
        page.read_text(encoding="utf-8").rstrip() + "\n- [stated] Human edit.\n",
        encoding="utf-8",
    )

    conflicted = store.add(
        [AddOperation(path="profile.md", if_version=stale, facts=[fact("Agent edit.")])]
    )
    latest = conflicted["latest"]
    assert isinstance(latest, dict)

    applied = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=str(latest["version"]),
                facts=[fact("Agent edit.")],
            )
        ]
    )
    assert applied["status"] == "applied"
    assert "Human edit." in page.read_text(encoding="utf-8")
    assert "Agent edit." in page.read_text(encoding="utf-8")


def test_page_snapshots_preserve_capacity_signal(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "preferences.md"
    page.write_text(
        render_memory_file(
            MemoryDocument(
                name="preferences",
                description="Preferences.",
                aliases=(),
                facts=tuple(
                    StoredFact(basis="stated", content=str(index) * 700)
                    for index in range(3)
                ),
            ),
            "preferences.md",
        ),
        encoding="utf-8",
    )
    snapshot = read_file(store, "preferences.md")
    assert snapshot["split_recommended"] is True

    page.write_text(
        page.read_text(encoding="utf-8").rstrip() + "\n- [stated] Concurrent edit.\n",
        encoding="utf-8",
    )
    conflicted = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=str(snapshot["version"]),
                facts=[fact("Agent edit.")],
            )
        ]
    )
    assert conflicted["status"] == "write_conflict"
    assert conflicted["latest"]["split_recommended"] is True  # type: ignore[index]


def test_edit_during_commit_is_detected(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    assert store.create([create("topics/late.md", "Original.")])["status"] == "applied"
    page = root / "topics/late.md"
    original_verify = store._verify_live_versions
    edited = False

    def verify_then_edit(initial, changed_paths) -> None:  # type: ignore[no-untyped-def]
        nonlocal edited
        original_verify(initial, changed_paths)
        if changed_paths == ["profile.md"] and not edited:
            page.write_text(
                page.read_text(encoding="utf-8").rstrip() + "\n- [stated] Late edit.\n",
                encoding="utf-8",
            )
            edited = True

    monkeypatch.setattr(store, "_verify_live_versions", verify_then_edit)
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("First agent edit.")],
            ),
            AddOperation(
                path="topics/late.md",
                if_version=version(store, "topics/late.md"),
                facts=[fact("Second agent edit.")],
            ),
        ]
    )
    assert result["status"] == "partial_commit"
    assert result["applied_paths"] == ["profile.md"]
    assert "files" not in result
    assert "Late edit." in page.read_text(encoding="utf-8")
    assert "Second agent edit." not in page.read_text(encoding="utf-8")


def test_move_fact(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2030-03-04")
    assert (
        store.create(
            [
                CreateOperation(
                    path="topics/source.md",
                    description="Source.",
                    aliases=[],
                    facts=[fact("Stay."), fact("Move me.")],
                ),
                create("areas/destination.md", "Keep me."),
            ]
        )["status"]
        == "applied"
    )
    moved = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                source_description="Source after move.",
                description="Destination after move.",
                facts=[fact("Move me.")],
            )
        ]
    )
    assert moved["status"] == "applied"
    source_page = read_file(store, "topics/source.md")
    assert source_page["description"] == "Source after move."
    source_facts = source_page["facts"]
    assert isinstance(source_facts, list)
    assert [item["content"] for item in source_facts] == ["Stay."]
    destination_page = read_file(store, "areas/destination.md")
    assert destination_page["description"] == "Destination after move."
    destination_facts = destination_page["facts"]
    assert isinstance(destination_facts, list)
    assert {item["content"] for item in destination_facts} == {
        "Keep me.",
        "Move me.",
    }
    moved_fact = next(
        item for item in destination_facts if item["content"] == "Move me."
    )
    assert moved_fact["date"] == "2030-03-04"
    snapshots = {item["path"]: item for item in moved["files"]}  # type: ignore[index]
    chained = store.add(
        [
            AddOperation(
                path="areas/destination.md",
                if_version=snapshots["areas/destination.md"]["version"],
                facts=[fact("Chained after move.")],
            )
        ]
    )
    assert chained["status"] == "applied"


def test_move_rejects_emptying_source_and_preserves_both_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert (
        store.create(
            [
                create("topics/source.md", "Only source fact."),
                create("areas/destination.md", "Destination fact."),
            ]
        )["status"]
        == "applied"
    )
    source = root / "topics" / "source.md"
    destination = root / "areas" / "destination.md"
    before = (source.read_bytes(), destination.read_bytes())

    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[selector("Only source fact.")],
            )
        ]
    )

    assert result["status"] == "invalid_entry"
    assert "leave at least one Fact" in str(result["message"])
    assert result["recovery"]
    assert (source.read_bytes(), destination.read_bytes()) == before


def test_move_to_new_page_rejects_emptying_source_without_creating_destination(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert store.create([create("topics/source.md", "Only source fact.")])[
        "status"
    ] == "applied"
    source = root / "topics" / "source.md"
    before = source.read_bytes()

    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                new_path="areas/new.md",
                description="New destination.",
                aliases=[],
                facts=[selector("Only source fact.")],
            )
        ]
    )

    assert result["status"] == "invalid_entry"
    assert source.read_bytes() == before
    assert not (root / "areas" / "new.md").exists()


def test_move_multiple_facts_between_same_pages_in_one_operation(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert (
        store.create(
            [
                CreateOperation(
                    path="topics/source.md",
                    description="Move related facts together.",
                    aliases=[],
                    facts=[fact("Stay."), fact("Move one."), fact("Move two.")],
                ),
                create("areas/destination.md", "Keep me."),
            ]
        )["status"]
        == "applied"
    )

    moved = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[fact("Move one."), fact("Move two.")],
            )
        ]
    )

    assert moved["status"] == "applied"
    source_facts = read_file(store, "topics/source.md")["facts"]
    assert isinstance(source_facts, list)
    assert [item["content"] for item in source_facts] == ["Stay."]
    destination_facts = read_file(store, "areas/destination.md")["facts"]
    assert isinstance(destination_facts, list)
    assert [item["content"] for item in destination_facts] == [
        "Keep me.",
        "Move one.",
        "Move two.",
    ]
    assert moved["mutations"][0]["receipt"] == (  # type: ignore[index]
        "`🧠 move [topics/source.md]: Move one. · Move two.`"
    )


def test_move_duplicate_page_in_batch_explains_recovery(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert (
        store.create(
            [
                CreateOperation(
                    path="topics/source.md",
                    description="Source.",
                    aliases=[],
                    facts=[fact("Move one."), fact("Move two.")],
                ),
                create("areas/destination.md", "Keep me."),
            ]
        )["status"]
        == "applied"
    )
    source_version = version(store, "topics/source.md")
    destination_version = version(store, "areas/destination.md")
    destination_before = (root / "areas" / "destination.md").read_bytes()

    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=source_version,
                destination_path="areas/destination.md",
                destination_version=destination_version,
                facts=[fact("Move one.")],
            ),
            MoveOperation(
                source_path="topics/source.md",
                source_version=source_version,
                destination_path="areas/destination.md",
                destination_version=destination_version,
                facts=[fact("Move two.")],
            ),
        ]
    )

    assert result["status"] == "duplicate_target"
    assert "all exact Facts" in str(result["recovery"])
    source_facts = read_file(store, "topics/source.md")["facts"]
    assert isinstance(source_facts, list)
    assert [item["content"] for item in source_facts] == [
        "Move one.",
        "Move two.",
    ]
    assert (root / "areas" / "destination.md").read_bytes() == destination_before


def test_move_multiple_facts_is_preflighted_before_commit(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert (
        store.create(
            [
                create("topics/source.md", "Move me."),
                create("areas/destination.md", "Keep me."),
            ]
        )["status"]
        == "applied"
    )

    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[fact("Move me."), fact("Missing fact.")],
            )
        ]
    )

    assert result["status"] == "not_found"
    assert "latest source Page Snapshot" in str(result["recovery"])
    source_facts = read_file(store, "topics/source.md")["facts"]
    destination_facts = read_file(store, "areas/destination.md")["facts"]
    assert isinstance(source_facts, list)
    assert isinstance(destination_facts, list)
    assert [item["content"] for item in source_facts] == ["Move me."]
    assert [item["content"] for item in destination_facts] == ["Keep me."]


def test_rename_is_local_and_preserves_old_name_as_alias(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2030-03-04")
    assert (
        store.create(
            [
                create("topics/source.md", "Source fact."),
                create("areas/reference.md", "See [[topics/source]]."),
            ]
        )["status"]
        == "applied"
    )
    reference_before = (root / "areas/reference.md").read_text(encoding="utf-8")
    renamed = store.rename(
        [
            RenameOperation(
                path="topics/source.md",
                if_version=version(store, "topics/source.md"),
                new_path="people/renamed.md",
            )
        ]
    )
    assert renamed["status"] == "applied"
    assert not (root / "topics/source.md").exists()
    snapshot = renamed["files"][0]  # type: ignore[index]
    chained = store.add(
        [
            AddOperation(
                path="people/renamed.md",
                if_version=snapshot["version"],
                facts=[fact("Chained after rename.")],
            )
        ]
    )
    assert chained["status"] == "applied"
    assert read_file(store, "people/renamed.md")["aliases"] == ["source"]
    renamed_facts = read_file(store, "people/renamed.md")["facts"]
    assert isinstance(renamed_facts, list)
    assert renamed_facts[0]["date"] == "2030-03-04"
    assert (root / "areas/reference.md").read_text(encoding="utf-8") == reference_before


def test_rename_can_promote_an_existing_alias(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert (
        store.create([create("topics/source.md", "Source fact.", ["assistant"])])[
            "status"
        ]
        == "applied"
    )
    renamed = store.rename(
        [
            RenameOperation(
                path="topics/source.md",
                if_version=version(store, "topics/source.md"),
                new_path="topics/assistant.md",
            )
        ]
    )
    assert renamed["status"] == "applied"
    assert read_file(store, "topics/assistant.md")["aliases"] == ["source"]


def test_rename_same_stem_across_scopes_preserves_page(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2030-03-04")
    assert store.create(
        [create("topics/source.md", "Source fact.", ["origin"])]
    )["status"] == "applied"

    renamed = store.rename(
        [
            RenameOperation(
                path="topics/source.md",
                if_version=version(store, "topics/source.md"),
                new_path="people/source.md",
            )
        ]
    )

    assert renamed["status"] == "applied"
    assert not (root / "topics/source.md").exists()
    item = read_file(store, "people/source.md")
    assert item["name"] == "source"
    assert item["description"] == "Route topics/source.md."
    assert item["aliases"] == ["origin"]
    assert item["facts"] == [
        {"basis": "stated", "content": "Source fact.", "date": "2030-03-04"}
    ]


def test_overlimit_rename_reports_capacity_without_target_path_mismatch(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    source = root / "topics" / "over.md"
    source.write_text(
        render_memory_file(
            MemoryDocument(
                name="over",
                description="Over limit.",
                aliases=(),
                facts=(
                    StoredFact(basis="stated", content="a" * 4096),
                    StoredFact(basis="stated", content="b" * 900),
                ),
            ),
            "topics/over.md",
        ),
        encoding="utf-8",
    )
    assert len(source.read_text(encoding="utf-8")) > memory_module.DYNAMIC_PAGE_LIMIT

    renamed = store.rename(
        [
            RenameOperation(
                path="topics/over.md",
                if_version=version(store, "topics/over.md"),
                new_path="topics/x.md",
            )
        ]
    )

    assert renamed["status"] == "capacity_exceeded"
    assert renamed["path"] == "topics/x.md"
    assert source.is_file()
    assert not (root / "topics" / "x.md").exists()


def test_rename_requires_alias_slot_to_preserve_old_name(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    aliases = [f"alias-{index}" for index in range(6)]
    assert (
        store.create([create("topics/source.md", "Source fact.", aliases)])["status"]
        == "applied"
    )

    renamed = store.rename(
        [
            RenameOperation(
                path="topics/source.md",
                if_version=version(store, "topics/source.md"),
                new_path="topics/renamed.md",
            )
        ]
    )

    assert renamed["status"] == "capacity_exceeded"
    assert renamed["limit"] == 6
    assert "leave one slot" in str(renamed["recovery"])
    assert (root / "topics" / "source.md").is_file()
    assert not (root / "topics" / "renamed.md").exists()


def test_rename_batch_rejects_reusing_any_old_or_new_path(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert store.create(
        [create("topics/a.md", "A."), create("topics/c.md", "C.")]
    )["status"] == "applied"
    before = {
        path: (root / path).read_bytes() for path in ("topics/a.md", "topics/c.md")
    }

    result = store.rename(
        [
            RenameOperation(
                path="topics/a.md",
                if_version=version(store, "topics/a.md"),
                new_path="topics/b.md",
            ),
            RenameOperation(
                path="topics/c.md",
                if_version=version(store, "topics/c.md"),
                new_path="topics/a.md",
            ),
        ]
    )

    assert result["status"] == "duplicate_target"
    assert all((root / path).read_bytes() == content for path, content in before.items())
    assert not (root / "topics" / "b.md").exists()


def test_delete_requires_authorization_and_protects_fixed_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    with pytest.raises(ValidationError):
        DeletePageOperation.model_validate(
            {
                "path": "topics/page.md",
                "if_version": "sha256:" + "0" * 64,
                "target": "page",
                "authorization": "implicit",
            }
        )
    fixed = store.delete(
        [
            DeletePageOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                target="page",
                authorization="user_requested",
            )
        ]
    )
    assert fixed["status"] == "invalid_path"
    assert (
        store.create([create("topics/delete.md", "Delete fact.")])["status"]
        == "applied"
    )
    deleted_fact = store.delete(
        [
            DeleteFactOperation(
                path="topics/delete.md",
                if_version=version(store, "topics/delete.md"),
                target="fact",
                fact=fact("Delete fact."),
                description="No facts remain.",
                authorization="user_requested",
            )
        ]
    )
    assert deleted_fact["status"] == "applied"
    assert (
        deleted_fact["files"][0]["description"] == "No facts remain."  # type: ignore[index]
    )
    deleted_page = store.delete(
        [
            DeletePageOperation(
                path="topics/delete.md",
                if_version=deleted_fact["files"][0]["version"],  # type: ignore[index]
                target="page",
                authorization="user_requested",
            )
        ]
    )
    assert deleted_page["status"] == "applied"
    assert deleted_page["files"] == []


def test_catalog_allows_cross_page_alias_collision(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.create(
        [
            create("topics/one.md", "One.", ["shared"]),
            create("topics/two.md", "Two.", ["Shared"]),
        ]
    )
    assert result["status"] == "applied"
    listed = store.list_files("topics")
    assert [item["aliases"] for item in listed["files"]] == [  # type: ignore[index]
        ["shared"],
        ["Shared"],
    ]


def test_fixed_page_hard_limit(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact(str(index) * 650) for index in range(3)],
            )
        ]
    )
    assert result["status"] == "capacity_exceeded"
    assert result["limit"] == 2000


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation is privileged")
def test_canonical_paths_and_symlinks_are_rejected(
    memory_store: tuple[Path, MemoryStore], tmp_path: Path
) -> None:
    root, store = memory_store
    assert store.read(["../outside.md"])["status"] == "invalid_path"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text(
        render_memory_file(
            MemoryDocument(
                name="leak",
                description="Outside Memory Root.",
                aliases=(),
                facts=(StoredFact(basis="stated", content="Must not leak."),),
            ),
            "topics/leak.md",
        ),
        encoding="utf-8",
    )
    topics = root / "topics"
    topics.rmdir()
    topics.symlink_to(outside, target_is_directory=True)
    listed = store.list_files("topics")
    assert listed["status"] == "invalid_source"
    assert listed["path"] == "topics"
    assert store.read(["topics/leak.md"])["status"] == "invalid_source"
    repaired = store.update(
        [
            RepairPageOperation(
                path="topics/leak.md",
                if_version="sha256:" + "0" * 64,
                target="repair",
            )
        ]
    )
    assert repaired["status"] == "invalid_source"
    assert "raw" not in repaired


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation is privileged")
def test_scoped_list_ignores_invalid_unrelated_scope(
    memory_store: tuple[Path, MemoryStore], tmp_path: Path
) -> None:
    root, store = memory_store
    assert store.create([create("topics/inside.md", "Inside.")])["status"] == "applied"
    outside = tmp_path / "outside-areas"
    outside.mkdir()
    (root / "areas").rmdir()
    (root / "areas").symlink_to(outside, target_is_directory=True)

    listed = store.list_files("topics")

    assert listed["status"] == "ok"
    assert [item["path"] for item in cast(list[dict[str, object]], listed["files"])] == [
        "topics/inside.md"
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation is privileged")
def test_page_symlink_is_rejected_by_list_read_repair_and_write(
    memory_store: tuple[Path, MemoryStore], tmp_path: Path
) -> None:
    root, store = memory_store
    outside = tmp_path / "outside.md"
    outside.write_text(
        render_memory_file(
            MemoryDocument(
                name="linked",
                description="Outside.",
                aliases=(),
                facts=(StoredFact(basis="stated", content="Outside fact."),),
            ),
            "topics/linked.md",
        ),
        encoding="utf-8",
    )
    linked = root / "topics" / "linked.md"
    linked.symlink_to(outside)

    assert store.list_files("topics")["status"] == "invalid_source"
    assert store.read(["topics/linked.md"])["status"] == "invalid_source"
    repaired = store.update(
        [
            RepairPageOperation(
                path="topics/linked.md",
                if_version="sha256:" + "0" * 64,
                target="repair",
            )
        ]
    )
    assert repaired["status"] == "invalid_source"
    added = store.add(
        [
            AddOperation(
                path="topics/linked.md",
                if_version="sha256:" + "0" * 64,
                facts=[fact("Do not write.")],
            )
        ]
    )
    assert added["status"] == "invalid_source"
    assert "Do not write." not in outside.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation is privileged")
def test_memory_root_replaced_by_symlink_is_rejected(
    memory_store: tuple[Path, MemoryStore], tmp_path: Path
) -> None:
    root, store = memory_store
    original = tmp_path / "original-memory"
    root.rename(original)
    outside = tmp_path / "outside-memory"
    outside.mkdir()
    root.symlink_to(outside, target_is_directory=True)

    assert store.list_files("topics")["status"] == "invalid_source"
    assert store.read(["profile.md"])["status"] == "invalid_source"
    created = store.create([create("topics/escape.md", "Must not escape.")])
    assert created["status"] == "invalid_source"
    assert not (outside / "topics" / "escape.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation is privileged")
def test_memory_store_constructed_from_symlink_root_is_rejected(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-memory"
    config = MemoryFilesConfig(root=str(outside))
    assert initialize_memory_tree(outside, config)["status"] == "applied"
    linked_root = tmp_path / "linked-memory"
    linked_root.symlink_to(outside, target_is_directory=True)
    linked_config = MemoryFilesConfig(root=str(linked_root))

    initialized = initialize_memory_tree(linked_root, linked_config)
    assert initialized["status"] == "invalid_source"
    store = MemoryStore(linked_root, linked_config)
    assert store.list_files("topics")["status"] == "invalid_source"
    created = store.create([create("topics/escape.md", "Must not escape.")])
    assert created["status"] == "invalid_source"
    assert not (outside / "topics" / "escape.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX FIFO")
def test_repair_rejects_fifo_without_blocking(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    fifo = root / "topics" / "pipe.md"
    mkfifo = getattr(os, "mkfifo", None)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    assert mkfifo is not None
    mkfifo(fifo)
    real_open = os.open

    def guarded_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == fifo.name and not flags & nonblock:
            raise AssertionError("FIFO must be opened non-blocking before fstat")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)

    result = store.update(
        [
            RepairPageOperation(
                path="topics/pipe.md",
                if_version="sha256:" + "0" * 64,
                target="repair",
            )
        ]
    )

    assert result["status"] == "invalid_source"


def test_legacy_environment_is_outside_catalog(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    environment = root / "environment"
    environment.mkdir()
    (environment / "macos.md").write_text("ignored\n", encoding="utf-8")
    listed = store.list_files("topics")
    assert listed["status"] == "ok"
    assert "environment/macos.md" not in {
        item["path"]
        for item in listed["files"]  # type: ignore[index]
    }


def test_changed_pages_are_canonicalized(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "preferences.md"
    text = page.read_text(encoding="utf-8").replace(
        'name: "preferences"', "name: preferences"
    )
    page.write_text(text, encoding="utf-8")
    result = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("Canonicalized fact.")],
            )
        ]
    )
    assert result["status"] == "applied"
    assert 'name: "preferences"' in page.read_text(encoding="utf-8")


def test_applied_mutations_return_receipts(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.create([create("topics/receipt.md", "Receipt fact.")])
    assert result["status"] == "applied"
    assert result["mutations"][0]["receipt"] == (  # type: ignore[index]
        "`🧠 create [topics/receipt.md]: Receipt fact.`"
    )


def test_applied_files_can_chain_mutations_without_read(
    memory_store: tuple[Path, MemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2032-03-04")
    added = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("Original preference.")],
            )
        ]
    )
    snapshot = added["files"][0]  # type: ignore[index]

    updated = store.update(
        [
            UpdateFactOperation(
                path="preferences.md",
                if_version=snapshot["version"],
                target="fact",
                old_fact=fact("Original preference."),
                new_fact=fact("Refined preference."),
            )
        ]
    )
    assert updated["status"] == "applied"
    assert updated["files"][0]["facts"][-1] == {  # type: ignore[index]
        "basis": "stated",
        "content": "Refined preference.",
        "date": "2032-03-04",
    }


def test_receipt_markdown_code_span_handles_backticks_and_html(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.create(
        [
            CreateOperation(
                path="topics/code.md",
                description="Code receipts.",
                aliases=[],
                facts=[fact("Use `code` here."), fact("Compare <a> & <b>.")],
            )
        ]
    )
    assert result["mutations"][0]["receipt"] == (  # type: ignore[index]
        "``🧠 create [topics/code.md]: Use `code` here. · Compare <a> & <b>.``"
    )


def test_receipt_markdown_code_span_preserves_trailing_backtick(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.create([create("topics/backtick.md", "Ends with `")])
    assert result["mutations"][0]["receipt"] == (  # type: ignore[index]
        "`` 🧠 create [topics/backtick.md]: Ends with ` ``"
    )


def test_read_rejects_duplicate_paths(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    assert store.read(["profile.md", "profile.md"])["status"] == "invalid_entry"


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support POSIX file modes"
)
def test_mutation_preserves_existing_file_mode(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "profile.md"
    page.chmod(0o644)
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("Keep the mode.")],
            )
        ]
    )
    assert result["status"] == "applied"
    assert page.stat().st_mode & 0o777 == 0o644


def test_interrupted_move_duplicates_before_it_can_lose_a_fact(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    assert (
        store.create(
            [
                CreateOperation(
                    path="topics/source.md",
                    description="Safe source.",
                    aliases=[],
                    facts=[fact("Stay safely."), fact("Move safely.")],
                ),
                create("areas/destination.md", "Keep."),
            ]
        )["status"]
        == "applied"
    )
    original_replace = os.replace

    def fail_source_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == root / "topics/source.md":
            raise OSError("simulated source replace failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_source_replace)
    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[fact("Move safely.")],
            )
        ]
    )
    assert result["status"] == "partial_commit"
    assert result["applied_paths"] == ["areas/destination.md"]
    assert "Move safely." in str(read_file(store, "topics/source.md")["facts"])
    assert "Move safely." in str(read_file(store, "areas/destination.md")["facts"])


def test_move_destination_failure_leaves_source_and_destination_unchanged(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    assert store.create(
        [
            CreateOperation(
                path="topics/source.md",
                description="Safe source.",
                aliases=[],
                facts=[fact("Stay safely."), fact("Move safely.")],
            ),
            create("areas/destination.md", "Keep."),
        ]
    )["status"] == "applied"
    source = root / "topics" / "source.md"
    destination = root / "areas" / "destination.md"
    before = (source.read_bytes(), destination.read_bytes())
    original_replace = os.replace

    def fail_destination(source_path: str | Path, destination_path: str | Path) -> None:
        if Path(destination_path) == destination:
            raise OSError("simulated destination replace failure")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", fail_destination)
    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[selector("Move safely.")],
            )
        ]
    )

    assert result["status"] == "write_failed"
    assert (source.read_bytes(), destination.read_bytes()) == before


def test_new_move_destination_failure_leaves_source_unchanged(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    assert store.create(
        [
            CreateOperation(
                path="topics/source.md",
                description="Safe source.",
                aliases=[],
                facts=[fact("Stay safely."), fact("Move safely.")],
            )
        ]
    )["status"] == "applied"
    source = root / "topics" / "source.md"
    before = source.read_bytes()
    destination = root / "areas" / "new.md"
    original_replace = os.replace

    def fail_destination(source_path: str | Path, destination_path: str | Path) -> None:
        if Path(destination_path) == destination:
            raise OSError("simulated new destination replace failure")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", fail_destination)
    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                new_path="areas/new.md",
                description="New destination.",
                aliases=["new-alias"],
                facts=[selector("Move safely.")],
            )
        ]
    )

    assert result["status"] == "write_failed"
    assert source.read_bytes() == before
    assert not destination.exists()


def test_atomic_replace_failure_leaves_no_temp_file(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    original_replace = os.replace

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == root / "profile.md":
            raise OSError("simulated replace failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_replace)
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("Must not persist.")],
            )
        ]
    )
    assert result["status"] == "write_failed"
    assert not list(root.glob(".profile.md.*.tmp"))


def test_add_duplicate_path_in_batch_returns_duplicate_target(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    result = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("First fact.")],
            ),
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("Second fact.")],
            ),
        ]
    )
    assert result["status"] == "duplicate_target"
    assert "more than once" in str(result.get("message", ""))
    # Verify no files were written
    content = (root / "preferences.md").read_text(encoding="utf-8")
    assert "First fact." not in content
    assert "Second fact." not in content


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support POSIX file modes"
)
def test_initialize_uses_private_posix_modes(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "memory"
    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))
    assert result["status"] == "applied"
    assert root.stat().st_mode & 0o777 == memory_module.NEW_DIRECTORY_MODE
    for directory in ("topics", "areas", "people"):
        assert (
            root / directory
        ).stat().st_mode & 0o777 == memory_module.NEW_DIRECTORY_MODE
    for relative in ("profile.md", "preferences.md", ".keepygaga.lock"):
        assert (root / relative).stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support POSIX file modes"
)
def test_existing_overbroad_lock_mode_is_preserved(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    lock_path = root / ".keepygaga.lock"
    lock_path.chmod(0o644)
    listed = store.list_files("topics")
    assert listed["status"] == "ok"
    assert lock_path.stat().st_mode & 0o777 == 0o644
    inspected = store.inspect()
    warnings = inspected["permission_warnings"]
    assert isinstance(warnings, list)
    assert any(item["path"] == str(lock_path) for item in warnings)  # type: ignore[index]


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support POSIX file modes"
)
def test_missing_lock_is_recreated_with_private_mode(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    lock_path = root / ".keepygaga.lock"
    lock_path.unlink()
    listed = store.list_files("topics")
    assert listed["status"] == "ok"
    assert lock_path.stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support POSIX file modes"
)
def test_create_uses_private_posix_mode_without_changing_existing_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    profile = root / "profile.md"
    profile.chmod(0o644)
    result = store.create([create("topics/private.md", "New private page.")])
    assert result["status"] == "applied"
    assert (
        root / "topics/private.md"
    ).stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE
    assert profile.stat().st_mode & 0o777 == 0o644


def test_create_rejects_more_than_max_dynamic_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    limit = memory_module.DYNAMIC_PAGE_LIMITS["topics"]
    existing = limit - 1
    for index in range(existing):
        path = f"topics/page-{index}.md"
        assert store.create([create(path, f"Fact {index}.")])["status"] == "applied"
    overflow = store.create(
        [
            create("topics/limit-a.md", "First extra."),
            create("topics/limit-b.md", "Second extra."),
        ]
    )
    assert overflow["status"] == "capacity_exceeded"
    assert overflow["current"] == existing
    assert overflow["limit"] == limit
    assert overflow["scope"] == "topics"
    assert "topics/limit-a.md" not in {
        item["path"]
        for item in store.list_files("topics")["files"]  # type: ignore[index]
    }
    allowed = store.create([create("topics/limit-a.md", "Last allowed.")])
    assert allowed["status"] == "applied"
    blocked = store.create([create("topics/limit-b.md", "Over the limit.")])
    assert blocked["status"] == "capacity_exceeded"
    assert blocked["current"] == limit
    listed = store.list_files("topics")
    assert listed["status"] == "ok"


def test_dynamic_page_limits_are_literal_contract() -> None:
    assert memory_module.DYNAMIC_PAGE_LIMITS == {
        "topics": 50,
        "areas": 50,
        "people": 100,
    }


def test_configured_scope_and_page_limits_control_store_behavior(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    config = MemoryFilesConfig(
        root=str(root),
        limits=MemoryLimitsConfig(
            fixed_page_chars=100,
            dynamic_page_chars=120,
            topics_pages=1,
            areas_pages=2,
            people_pages=3,
        ),
    )
    assert initialize_memory_tree(root, config)["status"] == "applied"
    store = MemoryStore(root, config)

    first = store.create([create("topics/first.md", "Short.")])
    assert first["status"] == "applied"
    second = store.create([create("topics/second.md", "Blocked by scope.")])
    assert second["status"] == "capacity_exceeded"
    assert second["limit"] == 1

    oversized = store.create([create("areas/oversized.md", "x" * 100)])
    assert oversized["status"] == "capacity_exceeded"
    assert oversized["limit"] == 120

    inspected = store.inspect()
    assert inspected["max_dynamic_pages"] == {
        "topics": 1,
        "areas": 2,
        "people": 3,
    }
    capacities = cast(dict[str, dict[str, object]], inspected["capacities"])
    assert capacities[str(root / "profile.md")]["limit"] == 100


def test_full_target_scope_blocks_new_move_and_cross_scope_rename(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    for index in range(50):
        path = f"areas/manual-{index}.md"
        (root / path).write_text(
            render_memory_file(
                MemoryDocument(
                    name=f"manual-{index}",
                    description="Manual area.",
                    aliases=(),
                    facts=(StoredFact(basis="stated", content=f"Area {index}."),),
                ),
                path,
            ),
            encoding="utf-8",
        )
    assert store.create(
        [
            CreateOperation(
                path="topics/source.md",
                description="Source.",
                aliases=[],
                facts=[fact("Stay."), fact("Move.")],
            )
        ]
    )["status"] == "applied"

    moved = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                new_path="areas/new.md",
                description="New area.",
                aliases=[],
                facts=[selector("Move.")],
            )
        ]
    )
    assert moved["status"] == "capacity_exceeded"
    assert moved["scope"] == "areas"
    assert moved["current"] == 50
    assert moved["limit"] == 50
    assert moved["recovery"]

    renamed = store.rename(
        [
            RenameOperation(
                path="topics/source.md",
                if_version=version(store, "topics/source.md"),
                new_path="areas/source.md",
            )
        ]
    )
    assert renamed["status"] == "capacity_exceeded"
    assert renamed["scope"] == "areas"
    assert not (root / "areas" / "new.md").exists()
    assert (root / "topics" / "source.md").is_file()


def test_create_capacity_check_runs_after_path_validation(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    limit = memory_module.DYNAMIC_PAGE_LIMITS["topics"]
    for index in range(limit):
        path = f"topics/page-{index}.md"
        assert store.create([create(path, f"Fact {index}.")])["status"] == "applied"
    invalid = store.create([create("profile.md", "Fixed page.")])
    assert invalid["status"] == "invalid_path"
    duplicate = store.create([create("topics/page-0.md", "Already there.")])
    assert duplicate["status"] == "already_exists"
    overflow = store.create([create("topics/limit-b.md", "Over the limit.")])
    assert overflow["status"] == "capacity_exceeded"


def test_existing_tree_over_dynamic_page_limit_remains_readable(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    limit = memory_module.DYNAMIC_PAGE_LIMITS["topics"]
    for index in range(limit + 1):
        path = root / "topics" / f"manual-{index}.md"
        path.write_text(
            render_memory_file(
                MemoryDocument(
                    name=f"manual-{index}",
                    description=f"Manual page {index}.",
                    aliases=(),
                    facts=(
                        StoredFact(basis="stated", content=f"Manual fact {index}."),
                    ),
                ),
                f"topics/manual-{index}.md",
            ),
            encoding="utf-8",
        )
    inspected = store.inspect()
    assert inspected["status"] == "ok"
    dynamic_pages = cast(dict[str, int], inspected["dynamic_pages"])
    exceeded = cast(dict[str, bool], inspected["dynamic_page_limit_exceeded"])
    assert dynamic_pages["topics"] == limit + 1
    assert exceeded["topics"] is True
    listed = store.list_files("topics")
    assert listed["status"] == "ok"
    first = read_file(store, "topics/manual-0.md")
    renamed = store.rename(
        [
            RenameOperation(
                path="topics/manual-0.md",
                if_version=str(first["version"]),
                new_path="topics/manual-renamed.md",
            )
        ]
    )
    assert renamed["status"] == "applied"
    blocked = store.create([create("topics/another.md", "Still blocked.")])
    assert blocked["status"] == "capacity_exceeded"


def test_fact_dates_are_optional_validated_and_rendered() -> None:
    legacy = MemoryDocument(
        name="example",
        description="Example.",
        aliases=(),
        facts=(StoredFact(basis="stated", content="Legacy."),),
    )
    assert "- [stated] Legacy.\n" in render_memory_file(legacy, "topics/example.md")
    dated = MemoryDocument(
        name="example",
        description="Example.",
        aliases=(),
        facts=(
            StoredFact(
                basis="observed",
                content="Dated inference.",
                date="2026-09-02",
            ),
        ),
    )
    rendered = render_memory_file(dated, "topics/example.md")
    assert "- [observed] Dated inference. [2026-09-02]\n" in rendered
    assert parse_memory_file(rendered, "topics/example.md") == dated
    invalid = rendered.replace("2026-09-02", "2026-02-30")
    with pytest.raises(memory_module.MemoryValidationError):
        parse_memory_file(invalid, "topics/example.md")
    duplicate_with_different_dates = (
        "---\nname: example\ndescription: Example.\naliases: []\n---\n\n"
        "- [stated] Same Fact. [2026-09-01]\n"
        "- [stated] Same Fact. [2026-09-02]\n"
    )
    with pytest.raises(memory_module.MemoryValidationError):
        parse_memory_file(duplicate_with_different_dates, "topics/example.md")


def test_mutation_date_is_captured_once_and_move_preserves_it(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store = memory_store
    calls = 0

    def fixed_date() -> str:
        nonlocal calls
        calls += 1
        return "2030-01-02"

    monkeypatch.setattr(memory_store_module, "_local_date", fixed_date)
    created = store.create(
        [
            CreateOperation(
                path="people/person.md",
                description="Known person.",
                aliases=["P"],
                facts=[fact("Core fact."), fact("Work fact.", "observed")],
            ),
            create("topics/other.md", "Other fact."),
        ]
    )
    assert created["status"] == "applied"
    assert calls == 1
    assert read_file(store, "topics/other.md")["facts"] == [
        {"basis": "stated", "content": "Other fact.", "date": "2030-01-02"}
    ]
    monkeypatch.setattr(
        memory_store_module,
        "_local_date",
        lambda: pytest.fail("move must not generate a new Fact date"),
    )
    moved = store.move(
        [
            MoveOperation(
                source_path="people/person.md",
                source_version=version(store, "people/person.md"),
                new_path="people/person-work.md",
                description="Work context for this person.",
                aliases=["P"],
                facts=[fact("Work fact.", "observed")],
            )
        ]
    )
    assert moved["status"] == "applied"
    destination = read_file(store, "people/person-work.md")
    assert destination["name"] == "person-work"
    assert destination["description"] == "Work context for this person."
    assert destination["aliases"] == ["P"]
    assert destination["facts"] == [
        {
            "basis": "observed",
            "content": "Work fact.",
            "date": "2030-01-02",
        }
    ]
    source = read_file(store, "people/person.md")
    assert source["facts"] == [
        {"basis": "stated", "content": "Core fact.", "date": "2030-01-02"}
    ]


def test_multi_operation_add_and_update_each_capture_one_date(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store = memory_store
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2030-02-02")
    assert store.create(
        [create("topics/one.md", "One."), create("areas/two.md", "Two.")]
    )["status"] == "applied"
    calls = 0

    def add_date() -> str:
        nonlocal calls
        calls += 1
        return "2030-02-03"

    monkeypatch.setattr(memory_store_module, "_local_date", add_date)
    added = store.add(
        [
            AddOperation(
                path="topics/one.md",
                if_version=version(store, "topics/one.md"),
                facts=[fact("Added one.")],
            ),
            AddOperation(
                path="areas/two.md",
                if_version=version(store, "areas/two.md"),
                facts=[fact("Added two.")],
            ),
        ]
    )
    assert added["status"] == "applied"
    assert calls == 1
    assert {
        item["facts"][-1]["date"]  # type: ignore[index]
        for item in added["files"]  # type: ignore[union-attr]
    } == {"2030-02-03"}

    calls = 0

    def update_date() -> str:
        nonlocal calls
        calls += 1
        return "2030-02-04"

    monkeypatch.setattr(memory_store_module, "_local_date", update_date)
    updated = store.update(
        [
            UpdateFactOperation(
                path="topics/one.md",
                if_version=version(store, "topics/one.md"),
                target="fact",
                old_fact=selector("Added one."),
                new_fact=fact("Updated one."),
            ),
            UpdateFactOperation(
                path="areas/two.md",
                if_version=version(store, "areas/two.md"),
                target="fact",
                old_fact=selector("Added two."),
                new_fact=fact("Updated two."),
            ),
        ]
    )
    assert updated["status"] == "applied"
    assert calls == 1
    assert {
        item["facts"][-1]["date"]  # type: ignore[index]
        for item in updated["files"]  # type: ignore[union-attr]
    } == {"2030-02-04"}
    assert read_file(store, "topics/one.md")["facts"] == [
        {"basis": "stated", "content": "One.", "date": "2030-02-02"},
        {"basis": "stated", "content": "Updated one.", "date": "2030-02-04"},
    ]


def test_legacy_long_fact_can_be_selected_for_move_and_update(
    memory_store: tuple[Path, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, store = memory_store
    long_content = "L" * 900
    with pytest.raises(ValidationError):
        fact(long_content)
    legacy = root / "topics" / "legacy-long.md"
    legacy.write_text(
        render_memory_file(
            MemoryDocument(
                name="legacy-long",
                description="Legacy long Fact.",
                aliases=(),
                facts=(
                    StoredFact(basis="stated", content="Keep me."),
                    StoredFact(basis="observed", content=long_content),
                ),
            ),
            "topics/legacy-long.md",
        ),
        encoding="utf-8",
    )
    moved = store.move(
        [
            MoveOperation(
                source_path="topics/legacy-long.md",
                source_version=version(store, "topics/legacy-long.md"),
                new_path="topics/legacy-long-detail.md",
                description="Legacy detail.",
                aliases=[],
                facts=[selector(long_content, "observed")],
            )
        ]
    )
    assert moved["status"] == "applied"
    destination = read_file(store, "topics/legacy-long-detail.md")
    assert destination["facts"] == [
        {"basis": "observed", "content": long_content, "date": None}
    ]
    monkeypatch.setattr(memory_store_module, "_local_date", lambda: "2031-04-05")
    refined = store.update(
        [
            UpdateFactOperation(
                path="topics/legacy-long-detail.md",
                if_version=str(destination["version"]),
                target="fact",
                old_fact=selector(long_content, "observed"),
                new_fact=fact("Refined legacy detail.", "observed"),
            )
        ]
    )
    assert refined["status"] == "applied"
    assert read_file(store, "topics/legacy-long-detail.md")["facts"] == [
        {
            "basis": "observed",
            "content": "Refined legacy detail.",
            "date": "2031-04-05",
        }
    ]


def test_scoped_list_is_sorted_isolated_and_has_constant_aliases(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert (
        store.create(
            [create("topics/zeta.md", "Zeta."), create("topics/alpha.md", "Alpha.")]
        )["status"]
        == "applied"
    )
    (root / "areas" / "broken.md").write_text("not frontmatter\n", encoding="utf-8")

    listed = store.list_files("topics")

    assert listed == {
        "status": "ok",
        "files": [
            {
                "path": "topics/alpha.md",
                "description": "Route topics/alpha.md.",
                "aliases": [],
            },
            {
                "path": "topics/zeta.md",
                "description": "Route topics/zeta.md.",
                "aliases": [],
            },
        ],
    }
    assert store.list_files("areas")["status"] == "invalid_source"


def test_scoped_list_reports_unreadable_page_path_and_manual_recovery(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    (root / "people" / "broken.md").write_bytes(b"\xff")

    failure = store.list_files("people")

    assert failure["status"] == "invalid_source"
    assert failure["path"] == "people/broken.md"
    assert failure["repairable"] is False
    assert "Fix the exact page manually" in str(failure["recovery"])


def test_repair_is_explicit_versioned_and_semantics_preserving(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "repairable.md"
    original = (
        "---\n"
        'aliases: ["same", "same", "repairable"]\n'
        'description: "Repairable page."\n'
        'name: "repairable"\n'
        "---\n\n"
        "- [stated] Keep this fact. [2030-03-04]\n"
        "- [stated] Keep this fact. [2030-03-04]\n"
    )
    page.write_text(original, encoding="utf-8")

    failure = store.list_files("topics")

    assert failure["status"] == "invalid_source"
    assert failure["repairable"] is True
    assert failure["raw"] == original
    assert page.read_text(encoding="utf-8") == original
    repaired = store.update(
        [
            RepairPageOperation(
                path="topics/repairable.md",
                if_version=str(failure["version"]),
                target="repair",
            )
        ]
    )
    assert repaired["status"] == "applied"
    item = read_file(store, "topics/repairable.md")
    assert item["name"] == "repairable"
    assert item["description"] == "Repairable page."
    assert item["aliases"] == ["same"]
    assert item["facts"] == [
        {"basis": "stated", "content": "Keep this fact.", "date": "2030-03-04"}
    ]


def test_repair_rejects_page_that_scoped_list_accepts(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "valid.md"
    original = (
        "---\n"
        "name: valid\n"
        "description: Valid page.\n"
        "aliases: []\n"
        "---\n\n"
        "- [stated] Keep this fact. [2030-03-04]\n"
    )
    page.write_text(original, encoding="utf-8")
    assert store.list_files("topics")["status"] == "ok"

    repaired = store.update(
        [
            RepairPageOperation(
                path="topics/valid.md",
                if_version=version(store, "topics/valid.md"),
                target="repair",
            )
        ]
    )

    assert repaired["status"] == "invalid_entry"
    assert repaired["repairable"] is False
    assert page.read_text(encoding="utf-8") == original


def test_repair_stale_version_reports_conflict_without_raw(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "repairable.md"
    page.write_text(
        "---\naliases: []\ndescription: Repairable.\nname: repairable\n---\n",
        encoding="utf-8",
    )
    proposed = store.list_files("topics")
    assert proposed["repairable"] is True
    page.write_text(page.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed = page.read_bytes()

    result = store.update(
        [
            RepairPageOperation(
                path="topics/repairable.md",
                if_version=str(proposed["version"]),
                target="repair",
            )
        ]
    )

    assert result["status"] == "write_conflict"
    assert "raw" not in result
    assert result["version"] != proposed["version"]
    assert page.read_bytes() == changed


def test_repair_deleted_after_proposal_returns_actionable_not_found(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "repairable.md"
    page.write_text(
        "---\naliases: []\ndescription: Repairable.\nname: repairable\n---\n",
        encoding="utf-8",
    )
    proposed = store.list_files("topics")
    page.unlink()

    result = store.update(
        [
            RepairPageOperation(
                path="topics/repairable.md",
                if_version=str(proposed["version"]),
                target="repair",
            )
        ]
    )

    assert result["status"] == "not_found"
    assert result["path"] == "topics/repairable.md"
    assert "do not retry" in str(result["recovery"])


def test_repair_rejects_fixed_pages_not_proposed_by_scoped_list(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    result = store.update(
        [
            RepairPageOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                target="repair",
            )
        ]
    )

    assert result["status"] == "invalid_path"
    assert result["repairable"] is False


def test_list_does_not_propose_repair_that_cannot_reduce_page_capacity(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    raw = (
        "---\naliases: []\ndescription: x\nname: over\n---\n"
        f"- [stated] {'a' * 2463}\n"
        f"- [stated] {'b' * 2463}\n"
    )
    assert len(raw) == 4996
    (root / "topics" / "over.md").write_text(raw, encoding="utf-8")

    result = store.list_files("topics")

    assert result["status"] == "invalid_source"
    assert result["repairable"] is False
    assert "raw" not in result
    assert "version" not in result


def test_repair_cannot_be_mixed_with_semantic_update(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "repairable.md"
    original = "---\naliases: []\ndescription: Repairable.\nname: repairable\n---\n"
    page.write_text(original, encoding="utf-8")
    proposed = store.list_files("topics")
    profile = root / "profile.md"
    profile_before = profile.read_bytes()

    result = store.update(
        [
            RepairPageOperation(
                path="topics/repairable.md",
                if_version=str(proposed["version"]),
                target="repair",
            ),
            UpdatePageOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                target="page",
                description="Changed.",
            ),
        ]
    )

    assert result["status"] == "invalid_entry"
    assert page.read_text(encoding="utf-8") == original
    assert profile.read_bytes() == profile_before


def test_repair_batch_stale_second_page_writes_nothing(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    originals = {
        "topics/one.md": "---\naliases: []\ndescription: One.\nname: one\n---\n",
        "topics/two.md": "---\naliases: []\ndescription: Two.\nname: two\n---\n",
    }
    for path, raw in originals.items():
        (root / path).write_text(raw, encoding="utf-8")

    result = store.update(
        [
            RepairPageOperation(
                path="topics/one.md",
                if_version=codec.sha256_text(originals["topics/one.md"]),
                target="repair",
            ),
            RepairPageOperation(
                path="topics/two.md",
                if_version="sha256:" + "0" * 64,
                target="repair",
            ),
        ]
    )

    assert result["status"] == "write_conflict"
    assert all(
        (root / path).read_text(encoding="utf-8") == raw
        for path, raw in originals.items()
    )


def test_oversized_invalid_page_is_not_returned_or_mechanically_repaired(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "huge.md"
    page.write_text("not frontmatter\n" + "x" * 10_001, encoding="utf-8")

    listed = store.list_files("topics")

    assert listed["status"] == "invalid_source"
    assert listed["repairable"] is False
    assert "raw" not in listed
    assert "version" not in listed
    repaired = store.update(
        [
            RepairPageOperation(
                path="topics/huge.md",
                if_version=codec.sha256_text(page.read_text(encoding="utf-8")),
                target="repair",
            )
        ]
    )
    assert repaired["status"] == "capacity_exceeded"
    assert repaired["limit"] == 10_000
    assert "raw" not in repaired
    assert "version" not in repaired


def test_agent_metadata_limits_do_not_invalidate_legacy_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    accepted = store.create(
        [
            CreateOperation(
                path="topics/eighty.md",
                description="  " + "x" * 80 + "  ",
                aliases=[str(index) for index in range(6)],
                facts=[fact("Allowed.")],
            )
        ]
    )
    assert accepted["status"] == "applied"
    item = read_file(store, "topics/eighty.md")
    assert item["description"] == "x" * 80
    assert item["aliases"] == [str(index) for index in range(6)]
    with pytest.raises(ValidationError):
        CreateOperation(
            path="topics/too-long.md",
            description="x" * 81,
            aliases=[],
            facts=[fact("Rejected.")],
        )
    with pytest.raises(ValidationError):
        CreateOperation(
            path="topics/too-many.md",
            description="Aliases.",
            aliases=[str(index) for index in range(7)],
            facts=[fact("Rejected.")],
        )
    with pytest.raises(ValidationError, match="one non-empty line"):
        AddOperation(
            path="topics/eighty.md",
            if_version=version(store, "topics/eighty.md"),
            description="Two\nlines.",
            facts=[fact("Rejected.")],
        )
    legacy = root / "topics" / "legacy.md"
    legacy.write_text(
        render_memory_file(
            MemoryDocument(
                name="legacy",
                description="d" * 81,
                aliases=tuple(str(index) for index in range(7)),
                facts=(StoredFact(basis="stated", content="Readable."),),
            ),
            "topics/legacy.md",
        ),
        encoding="utf-8",
    )
    assert store.list_files("topics")["status"] == "ok"
    snapshot = read_file(store, "topics/legacy.md")
    rename_blocked = store.rename(
        [
            RenameOperation(
                path="topics/legacy.md",
                if_version=str(snapshot["version"]),
                new_path="topics/legacy-renamed.md",
            )
        ]
    )
    assert rename_blocked["status"] == "capacity_exceeded"
    assert rename_blocked["limit"] == 6
    partial_metadata_update = store.update(
        [
            UpdatePageOperation(
                path="topics/legacy.md",
                if_version=str(snapshot["version"]),
                target="page",
                description="Converged description.",
            )
        ]
    )
    assert partial_metadata_update["status"] == "invalid_entry"
    converged = store.update(
        [
            UpdatePageOperation(
                path="topics/legacy.md",
                if_version=str(snapshot["version"]),
                target="page",
                description="Converged description.",
                aliases=[str(index) for index in range(6)],
            )
        ]
    )
    assert converged["status"] == "applied"


def test_dynamic_page_limit_rejects_growth_but_allows_reduction(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    page = root / "topics" / "over.md"
    page.write_text(
        render_memory_file(
            MemoryDocument(
                name="over",
                description="Over capacity.",
                aliases=(),
                facts=tuple(
                    StoredFact(basis="stated", content=str(index) * 700)
                    for index in range(7)
                ),
            ),
            "topics/over.md",
        ),
        encoding="utf-8",
    )
    assert read_file(store, "topics/over.md")["split_recommended"] is True
    blocked = store.add(
        [
            AddOperation(
                path="topics/over.md",
                if_version=version(store, "topics/over.md"),
                facts=[fact("Cannot grow.")],
            )
        ]
    )
    assert blocked["status"] == "capacity_exceeded"
    before_metadata = page.read_bytes()
    metadata = store.update(
        [
            UpdatePageOperation(
                path="topics/over.md",
                if_version=version(store, "topics/over.md"),
                target="page",
                description="Short.",
            )
        ]
    )
    assert metadata["status"] == "capacity_exceeded"
    assert page.read_bytes() == before_metadata
    reduced = store.delete(
        [
            DeleteFactOperation(
                path="topics/over.md",
                if_version=version(store, "topics/over.md"),
                target="fact",
                fact=fact("0" * 700),
                authorization="user_requested",
            )
        ]
    )
    assert reduced["status"] == "applied"
    assert "split_recommended" not in read_file(store, "topics/over.md")


def test_move_cannot_hide_overlimit_destination_growth_with_raw_whitespace(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert (
        store.create(
            [
                CreateOperation(
                    path="topics/source.md",
                    description="Source.",
                    aliases=[],
                    facts=[fact("Stay."), fact("Move me.")],
                )
            ]
        )["status"]
        == "applied"
    )
    destination = root / "areas" / "over.md"
    destination.write_text(
        render_memory_file(
            MemoryDocument(
                name="over",
                description="Over capacity.",
                aliases=(),
                facts=tuple(
                    StoredFact(basis="stated", content=str(index) * 700)
                    for index in range(7)
                ),
            ),
            "areas/over.md",
        )
        + "\n" * 1000,
        encoding="utf-8",
    )
    source = root / "topics" / "source.md"
    before = (source.read_bytes(), destination.read_bytes())

    result = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/over.md",
                destination_version=version(store, "areas/over.md"),
                facts=[selector("Move me.")],
            )
        ]
    )

    assert result["status"] == "capacity_exceeded"
    assert (source.read_bytes(), destination.read_bytes()) == before


def test_yaml_scalar_compatibility(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    page = root / "topics" / "scalar.md"
    page.write_text(
        "---\nname: scalar\ndescription: 1e3\naliases: [1e4]\n---\n",
        encoding="utf-8",
    )
    read = store.read(["topics/scalar.md"])
    assert read["status"] == "ok"
    assert read["files"][0]["description"] == "1e3"  # type: ignore[index]
    assert read["files"][0]["aliases"] == ["1e4"]  # type: ignore[index]
