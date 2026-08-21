from __future__ import annotations

from pathlib import Path
from typing import cast

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
    assert result["schema"] == "keepygaga-doctor-v6"
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
    path.write_text(f'[memory]\nroot = "{memory_root}"\n', encoding="utf-8")
    result = run_doctor(path, project_root=tmp_path)
    assert result["status"] == "warning"


def test_doctor_reports_healthy_initialized_memory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config = MemoryFilesConfig(root=str(memory_root))
    assert initialize_memory_tree(memory_root, config)["status"] == "applied"
    path.write_text(f'[memory]\nroot = "{memory_root}"\n', encoding="utf-8")
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
