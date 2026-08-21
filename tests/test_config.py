from __future__ import annotations

from pathlib import Path

from keepygaga.config import load_config


def test_config_memory_defaults(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text("", encoding="utf-8")
    config = load_config(path)
    assert config.memory.root == ""


def test_load_config_reads_memory_root_and_ignores_legacy_hard_caps(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text(
        """
[memory]
root = "/tmp/memory"
root_limit = 1
page_limit = 1
content_limit = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert vars(config.memory) == {"root": "/tmp/memory"}


def test_load_config_missing_file_keeps_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")
    assert config.memory.root == ""
