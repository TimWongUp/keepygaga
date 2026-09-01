from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from keepygaga import codec, paths
from keepygaga import memory as memory_module
from keepygaga.config import MemoryFilesConfig
from keepygaga.memory import (
    AddOperation,
    CreateOperation,
    DeleteFactOperation,
    DeletePageOperation,
    Fact,
    MemoryDocument,
    MemoryStore,
    MoveOperation,
    RenameOperation,
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
    assert memory_module.MemoryDocument is codec.MemoryDocument
    assert memory_module.MAX_FACT_CONTENT_CHARS == codec.MAX_FACT_CONTENT_CHARS
    assert memory_module.PROFILE_FACT_CONTENT_LIMIT == codec.PROFILE_FACT_CONTENT_LIMIT
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


def test_core_memory_v1_contract_matches_current_page_format() -> None:
    documents = {
        "profile.md": MemoryDocument(
            name="profile",
            description="用户明确陈述的稳定身份、背景与长期角色。",
            aliases=("identity",),
            facts=(fact("Contract profile fact."),),
        ),
        "preferences.md": MemoryDocument(
            name="preferences",
            description="用户希望 Agent 长期遵循的回应方式、工作偏好与条件检索偏好。",
            aliases=("working-style",),
            facts=(fact("Contract preference fact."),),
        ),
    }
    for path, document in documents.items():
        canonical = (CONTRACT_ROOT / "canonical" / path).read_text(encoding="utf-8")
        legacy = (CONTRACT_ROOT / "legacy-sources" / path).read_text(
            encoding="utf-8"
        )
        assert canonical == render_memory_file(document, path)
        assert parse_memory_file(canonical, path) == document
        assert parse_memory_file(legacy, path) == document

    manifest = json.loads((CONTRACT_ROOT / "contract.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
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
        "max_content_chars": codec.MAX_FACT_CONTENT_CHARS,
        "length_checked": "before-trim",
        "duplicate_key": ["basis", "trimmed-content"],
        "profile_path": "profile.md",
        "profile_content_limit_chars": codec.PROFILE_FACT_CONTENT_LIMIT,
    }
    assert manifest["limits"] == {"max_dynamic_pages": memory_module.MAX_DYNAMIC_PAGES}
    assert Fact(basis="stated", content="  padded  ").content == "padded"
    with pytest.raises(ValidationError):
        Fact(basis="stated", content="  " + "x" * codec.MAX_FACT_CONTENT_CHARS)
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


def create(path: str, content: str, aliases: list[str] | None = None) -> CreateOperation:
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


def test_initialize_creates_minimal_tree(memory_store: tuple[Path, MemoryStore]) -> None:
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
    assert preferences.description == "用户希望 Agent 长期遵循的回应方式、工作偏好与条件检索偏好。"


def test_initialize_returns_optional_onboarding_for_created_pages(tmp_path: Path) -> None:
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
            facts=(fact("Human content."),),
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    original_mkdir = memory_module._mkdir_new

    def fail_areas(path: Path, *args, **kwargs) -> None:
        if path == root / "areas":
            raise PermissionError("simulated directory failure")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(memory_module, "_mkdir_new", fail_areas)

    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))

    assert result["status"] == "partial_commit"
    assert result["files"] == []
    assert result["directories"] == [str(root / "topics")]
    assert "onboarding" not in result


def test_initialize_partial_file_commit_does_not_offer_onboarding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "memory"
    original_create = memory_module._exclusive_create

    def fail_preferences(target: Path, text: str) -> bool:
        if target.name == "preferences.md":
            raise PermissionError("simulated page failure")
        return original_create(target, text)

    monkeypatch.setattr(memory_module, "_exclusive_create", fail_preferences)

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
    page = root / "preferences.md"
    page.write_text(
        page.read_text(encoding="utf-8") + "\nnot a fact\n", encoding="utf-8"
    )
    result = store.list_files()
    assert result["status"] == "invalid_source"
    assert result["path"] == "preferences.md"


def test_list_rejects_oversized_fact(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    page = root / "preferences.md"
    page.write_text(
        page.read_text(encoding="utf-8") + f"\n- [stated] {chr(120) * 4097}\n",
        encoding="utf-8",
    )
    result = store.list_files()
    assert result["status"] == "invalid_source"
    assert result["path"] == "preferences.md"


def test_list_is_minimal_and_read_is_structured(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert store.create([create("topics/ai.md", "AI fact.", ["人工智能"])])["status"] == "applied"
    listed = store.list_files()
    assert listed["status"] == "ok"
    by_path = {item["path"]: item for item in listed["files"]}  # type: ignore[index]
    assert set(by_path["profile.md"]) == {"path", "description"}
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
    assert store.read(["profile.md"] * 21)["status"] == "invalid_entry"


def test_create_add_update_and_page_metadata(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    created = store.create([create("areas/work.md", "First fact.")])
    assert created["status"] == "applied"
    added = store.add(
        [
            AddOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                facts=[fact("Second fact.")],
            )
        ]
    )
    assert added["status"] == "applied"
    updated = store.update(
        [
            UpdateFactOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                target="fact",
                old_fact=fact("First fact."),
                new_fact=fact("Refined first fact."),
            )
        ]
    )
    assert updated["status"] == "applied"
    metadata = store.update(
        [
            UpdatePageOperation(
                path="areas/work.md",
                if_version=version(store, "areas/work.md"),
                target="page",
                description="Work context.",
                aliases=["工作"],
            )
        ]
    )
    assert metadata["status"] == "applied"
    item = read_file(store, "areas/work.md")
    assert item["description"] == "Work context."
    assert item["aliases"] == ["工作"]
    assert item["facts"] == [
        {"basis": "stated", "content": "Refined first fact."},
        {"basis": "stated", "content": "Second fact."},
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
) -> None:
    _, store = memory_store
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
        {"basis": "stated", "content": "Prefers concise answers."}
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
        page.read_text(encoding="utf-8").rstrip()
        + "\n- [stated] Human edit.\n",
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
    applied = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=version(store, "preferences.md"),
                facts=[fact("x" * 2100)],
            )
        ]
    )
    snapshot = applied["files"][0]  # type: ignore[index]
    assert snapshot["split_recommended"] is True

    page = root / "preferences.md"
    page.write_text(
        page.read_text(encoding="utf-8").rstrip()
        + "\n- [stated] Concurrent edit.\n",
        encoding="utf-8",
    )
    conflicted = store.add(
        [
            AddOperation(
                path="preferences.md",
                if_version=snapshot["version"],
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
                page.read_text(encoding="utf-8").rstrip()
                + "\n- [stated] Late edit.\n",
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


def test_move_fact(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    assert store.create(
        [create("topics/source.md", "Move me."), create("areas/destination.md", "Keep me.")]
    )["status"] == "applied"
    moved = store.move(
        [
            MoveOperation(
                source_path="topics/source.md",
                source_version=version(store, "topics/source.md"),
                destination_path="areas/destination.md",
                destination_version=version(store, "areas/destination.md"),
                facts=[fact("Move me.")],
            )
        ]
    )
    assert moved["status"] == "applied"
    assert read_file(store, "topics/source.md")["facts"] == []
    destination_facts = read_file(store, "areas/destination.md")["facts"]
    assert isinstance(destination_facts, list)
    assert {item["content"] for item in destination_facts} == {
        "Keep me.",
        "Move me.",
    }
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


def test_move_multiple_facts_between_same_pages_in_one_operation(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert store.create(
        [
            CreateOperation(
                path="topics/source.md",
                description="Move related facts together.",
                aliases=[],
                facts=[fact("Move one."), fact("Move two.")],
            ),
            create("areas/destination.md", "Keep me."),
        ]
    )["status"] == "applied"

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
    assert read_file(store, "topics/source.md")["facts"] == []
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
    _, store = memory_store
    assert store.create(
        [
            CreateOperation(
                path="topics/source.md",
                description="Source.",
                aliases=[],
                facts=[fact("Move one."), fact("Move two.")],
            ),
            create("areas/destination.md", "Keep me."),
        ]
    )["status"] == "applied"
    source_version = version(store, "topics/source.md")
    destination_version = version(store, "areas/destination.md")

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


def test_move_multiple_facts_is_preflighted_before_commit(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert store.create(
        [
            create("topics/source.md", "Move me."),
            create("areas/destination.md", "Keep me."),
        ]
    )["status"] == "applied"

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
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    assert store.create(
        [
            create("topics/source.md", "Source fact."),
            create("areas/reference.md", "See [[topics/source]]."),
        ]
    )["status"] == "applied"
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
    assert (root / "areas/reference.md").read_text(encoding="utf-8") == reference_before


def test_rename_can_promote_an_existing_alias(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    assert store.create(
        [create("topics/source.md", "Source fact.", ["assistant"])]
    )["status"] == "applied"
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
    assert store.create([create("topics/delete.md", "Delete fact.")])["status"] == "applied"
    deleted_fact = store.delete(
        [
            DeleteFactOperation(
                path="topics/delete.md",
                if_version=version(store, "topics/delete.md"),
                target="fact",
                fact=fact("Delete fact."),
                authorization="user_requested",
            )
        ]
    )
    assert deleted_fact["status"] == "applied"
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


def test_catalog_rejects_alias_collision(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    result = store.create(
        [
            create("topics/one.md", "One.", ["shared"]),
            create("topics/two.md", "Two.", ["Shared"]),
        ]
    )
    assert result["status"] == "invalid_entry"
    assert store.read(["topics/one.md"])["status"] == "not_found"


def test_profile_hard_limit(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    result = store.add(
        [
            AddOperation(
                path="profile.md",
                if_version=version(store, "profile.md"),
                facts=[fact("x" * 301)],
            )
        ]
    )
    assert result["status"] == "invalid_entry"


def test_canonical_paths_and_symlinks_are_rejected(
    memory_store: tuple[Path, MemoryStore], tmp_path: Path
) -> None:
    root, store = memory_store
    assert store.read(["../outside.md"])["status"] == "invalid_path"
    outside = tmp_path / "outside"
    outside.mkdir()
    topics = root / "topics"
    topics.rmdir()
    topics.symlink_to(outside, target_is_directory=True)
    assert store.list_files()["status"] == "invalid_source"


def test_legacy_environment_is_outside_catalog(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    environment = root / "environment"
    environment.mkdir()
    (environment / "macos.md").write_text("ignored\n", encoding="utf-8")
    listed = store.list_files()
    assert listed["status"] == "ok"
    assert "environment/macos.md" not in {
        item["path"] for item in listed["files"]  # type: ignore[index]
    }


def test_changed_pages_are_canonicalized(memory_store: tuple[Path, MemoryStore]) -> None:
    root, store = memory_store
    page = root / "preferences.md"
    text = page.read_text(encoding="utf-8").replace("name: \"preferences\"", "name: preferences")
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


def test_applied_mutations_return_receipts(memory_store: tuple[Path, MemoryStore]) -> None:
    _, store = memory_store
    result = store.create([create("topics/receipt.md", "Receipt fact.")])
    assert result["status"] == "applied"
    assert result["mutations"][0]["receipt"] == (  # type: ignore[index]
        "`🧠 create [topics/receipt.md]: Receipt fact.`"
    )


def test_applied_files_can_chain_mutations_without_read(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
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


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support POSIX file modes')
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
    assert store.create(
        [create("topics/source.md", "Move safely."), create("areas/destination.md", "Keep.")]
    )["status"] == "applied"
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

@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support POSIX file modes')
def test_initialize_uses_private_posix_modes(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "memory"
    result = initialize_memory_tree(root, MemoryFilesConfig(root=str(root)))
    assert result["status"] == "applied"
    assert root.stat().st_mode & 0o777 == memory_module.NEW_DIRECTORY_MODE
    for directory in ("topics", "areas", "people"):
        assert (root / directory).stat().st_mode & 0o777 == memory_module.NEW_DIRECTORY_MODE
    for relative in ("profile.md", "preferences.md", ".keepygaga.lock"):
        assert (root / relative).stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support POSIX file modes')
def test_existing_overbroad_lock_mode_is_preserved(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    lock_path = root / ".keepygaga.lock"
    lock_path.chmod(0o644)
    listed = store.list_files()
    assert listed["status"] == "ok"
    assert lock_path.stat().st_mode & 0o777 == 0o644
    inspected = store.inspect()
    warnings = inspected["permission_warnings"]
    assert isinstance(warnings, list)
    assert any(item["path"] == str(lock_path) for item in warnings)  # type: ignore[index]


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support POSIX file modes')
def test_missing_lock_is_recreated_with_private_mode(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    lock_path = root / ".keepygaga.lock"
    lock_path.unlink()
    listed = store.list_files()
    assert listed["status"] == "ok"
    assert lock_path.stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support POSIX file modes')
def test_create_uses_private_posix_mode_without_changing_existing_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    root, store = memory_store
    profile = root / "profile.md"
    profile.chmod(0o644)
    result = store.create([create("topics/private.md", "New private page.")])
    assert result["status"] == "applied"
    assert (root / "topics/private.md").stat().st_mode & 0o777 == memory_module.NEW_FILE_MODE
    assert profile.stat().st_mode & 0o777 == 0o644


def test_create_rejects_more_than_max_dynamic_pages(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    existing = memory_module.MAX_DYNAMIC_PAGES - 1
    for index in range(existing):
        directory = ("topics", "areas", "people")[index % 3]
        path = f"{directory}/page-{index}.md"
        assert store.create([create(path, f"Fact {index}.")])["status"] == "applied"
    overflow = store.create(
        [
            create("topics/limit-a.md", "First extra."),
            create("topics/limit-b.md", "Second extra."),
        ]
    )
    assert overflow["status"] == "capacity_exceeded"
    assert overflow["current"] == existing
    assert overflow["limit"] == memory_module.MAX_DYNAMIC_PAGES
    assert "topics/limit-a.md" not in {
        item["path"] for item in store.list_files()["files"]  # type: ignore[index]
    }
    allowed = store.create([create("topics/limit-a.md", "Last allowed.")])
    assert allowed["status"] == "applied"
    blocked = store.create([create("topics/limit-b.md", "Over the limit.")])
    assert blocked["status"] == "capacity_exceeded"
    assert blocked["current"] == memory_module.MAX_DYNAMIC_PAGES
    listed = store.list_files()
    assert listed["status"] == "ok"



def test_create_capacity_check_runs_after_path_validation(
    memory_store: tuple[Path, MemoryStore],
) -> None:
    _, store = memory_store
    for index in range(memory_module.MAX_DYNAMIC_PAGES):
        directory = ("topics", "areas", "people")[index % 3]
        path = f"{directory}/page-{index}.md"
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
    for index in range(memory_module.MAX_DYNAMIC_PAGES + 1):
        path = root / "topics" / f"manual-{index}.md"
        path.write_text(
            render_memory_file(
                MemoryDocument(
                    name=f"manual-{index}",
                    description=f"Manual page {index}.",
                    aliases=(),
                    facts=(fact(f"Manual fact {index}."),),
                ),
                f"topics/manual-{index}.md",
            ),
            encoding="utf-8",
        )
    inspected = store.inspect()
    assert inspected["status"] == "ok"
    assert inspected["dynamic_pages"] == memory_module.MAX_DYNAMIC_PAGES + 1
    assert inspected["dynamic_page_limit_exceeded"] is True
    listed = store.list_files()
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
