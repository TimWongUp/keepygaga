from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from keepygaga.config import MemoryFilesConfig
from keepygaga.diagnostics import PUBLIC_MCP_TOOLS, run_doctor
from keepygaga.memory import initialize_memory_tree

EXPECTED_TOOLS = (
    "list",
    "read",
    "create",
    "add",
    "update",
    "move",
    "rename",
    "delete",
)


def test_doctor_reports_missing_memory_root_as_warning(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text("", encoding="utf-8")
    result = run_doctor(path, project_root=tmp_path)
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    assert result["schema"] == "keepygaga-doctor-v8"
    assert result["status"] == "warning"
    tools = result["tools"]
    assert isinstance(tools, list)
    assert tuple(tools) == EXPECTED_TOOLS
    assert tuple(PUBLIC_MCP_TOOLS) == EXPECTED_TOOLS
    assert memory["status"] == "warning"
    assert "not configured" in str(memory["message"])


def test_doctor_reports_uninitialized_tree_as_warning(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "missing"
    path.write_text(f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8")
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "warning"
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    assert memory["details"] == {
        "root": str(memory_root),
        "source_status": "not_initialized",
    }


def test_doctor_reports_file_memory_root_as_invalid_source(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    memory_root.write_text("not a directory\n", encoding="utf-8")
    path.write_text(f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8")

    result = run_doctor(path, project_root=tmp_path)

    assert result["status"] == "error"
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    assert memory["details"] == {
        "root": str(memory_root),
        "source_status": "invalid_source",
    }


def test_doctor_reports_healthy_initialized_memory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(memory_root))
    assert initialize_memory_tree(memory_root, config)["status"] == "applied"
    path.write_text(f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8")
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "ok"
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    assert memory["status"] == "ok"


def test_doctor_config_error_returns_error(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text("not toml [", encoding="utf-8")
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "error"
    tools = result["tools"]
    assert isinstance(tools, list)
    assert tuple(tools) == EXPECTED_TOOLS
    checks = cast(list[dict[str, object]], result["checks"])
    assert checks[0]["id"] == "config"
    assert checks[0]["status"] == "error"


def test_doctor_warns_when_dynamic_page_limit_is_exceeded(tmp_path: Path) -> None:
    from keepygaga import memory as memory_module
    from keepygaga.codec import MemoryDocument
    from keepygaga.memory import StoredFact, render_memory_file

    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(memory_root))
    assert initialize_memory_tree(memory_root, config)["status"] == "applied"
    limit = memory_module.DYNAMIC_PAGE_LIMITS["topics"]
    for index in range(limit + 1):
        page = memory_root / "topics" / f"manual-{index}.md"
        page.write_text(
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
    path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "warning"
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    details = cast(dict[str, object], memory["details"])
    exceeded = cast(dict[str, bool], details["dynamic_page_limit_exceeded"])
    dynamic_pages = cast(dict[str, int], details["dynamic_pages"])
    assert exceeded["topics"] is True
    assert dynamic_pages["topics"] == limit + 1


@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="Windows does not support POSIX file modes",
)
def test_doctor_warns_about_overbroad_existing_permissions(tmp_path: Path) -> None:
    import os

    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(memory_root))
    assert initialize_memory_tree(memory_root, config)["status"] == "applied"
    os.chmod(memory_root / "profile.md", 0o644)
    path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "warning"
    checks = cast(list[dict[str, object]], result["checks"])
    memory = next(item for item in checks if item["id"] == "memory_tree")
    details = cast(dict[str, object], memory["details"])
    warnings = details["permission_warnings"]
    assert isinstance(warnings, list)
    assert any(
        item["path"] == str(memory_root / "profile.md")
        for item in warnings  # type: ignore[index]
    )
    assert (memory_root / "profile.md").stat().st_mode & 0o777 == 0o644
