from __future__ import annotations

from pathlib import Path

import pytest

from keepygaga.config import MemoryLimitsConfig, load_config


def test_config_memory_defaults(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text("", encoding="utf-8")
    config = load_config(path)
    assert config.memory.root == ""
    assert config.memory.limits == MemoryLimitsConfig()
    assert config.limits_source == "defaults"


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
    assert config.memory.root == "/tmp/memory"
    assert config.memory.limits == MemoryLimitsConfig()


def test_load_config_reads_partial_memory_limit_overrides(tmp_path: Path) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text(
        """
[memory]
root = "/tmp/memory"

[memory.limits]
fixed_page_chars = 2500
topics_pages = 75
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.memory.limits.fixed_page_chars == 2500
    assert config.memory.limits.dynamic_page_chars == 5000
    assert config.memory.limits.topics_pages == 75
    assert config.limits_source == str(path)


@pytest.mark.parametrize(
    "setting",
    (
        "topics_pages = 0",
        "areas_pages = -1",
        'people_pages = "many"',
        "fixed_page_chars = true",
        "unknown_limit = 5",
    ),
)
def test_load_config_rejects_invalid_memory_limits(
    tmp_path: Path, setting: str
) -> None:
    path = tmp_path / "keepygaga.toml"
    path.write_text(
        f"[memory]\nroot = '/tmp/memory'\n[memory.limits]\n{setting}\n",
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError), match="memory.limits"):
        load_config(path)


def test_load_config_missing_file_keeps_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")
    assert config.memory.root == ""


def test_load_config_uses_environment_path(
    tmp_path: Path, monkeypatch,
) -> None:
    path = tmp_path / "environment.toml"
    path.write_text('[memory]\nroot = "/environment/memory"\n', encoding="utf-8")
    monkeypatch.setenv("KEEPYGAGA_CONFIG", str(path))

    assert load_config().memory.root == "/environment/memory"


def test_relative_environment_path_resolves_from_working_directory(
    tmp_path: Path, monkeypatch,
) -> None:
    path = tmp_path / "environment.toml"
    path.write_text('[memory]\nroot = "/relative/memory"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KEEPYGAGA_CONFIG", path.name)

    assert load_config().memory.root == "/relative/memory"


def test_explicit_config_path_overrides_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    environment_path = tmp_path / "environment.toml"
    environment_path.write_text(
        '[memory]\nroot = "/environment/memory"\n', encoding="utf-8"
    )
    explicit_path = tmp_path / "explicit.toml"
    explicit_path.write_text(
        '[memory]\nroot = "/explicit/memory"\n', encoding="utf-8"
    )
    monkeypatch.setenv("KEEPYGAGA_CONFIG", str(environment_path))

    assert load_config(explicit_path).memory.root == "/explicit/memory"
