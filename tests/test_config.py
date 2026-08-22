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
