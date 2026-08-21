from pathlib import Path

import pytest

from keepygaga import cli


def test_no_subcommand_prints_help(capsys) -> None:
    assert cli.main([]) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "doctor" in captured.out
    assert "memory" in captured.out


def test_unknown_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.main(["unknown"])


def test_memory_init_initializes_fixed_pages(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0
    assert (memory_root / "profile.md").is_file()
    assert (memory_root / "preferences.md").is_file()


def test_memory_init_refuses_unconfigured_root(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    captured = capsys.readouterr()
    assert '"status": "invalid_source"' in captured.out


def test_doctor_prints_json_and_reports_eight_tools(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root}"\n',
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0

    assert cli.main(["--config", str(config_path), "doctor"]) == 0
    captured = capsys.readouterr()
    assert '"status": "ok"' in captured.out
    assert '"tools"' in captured.out
    assert '"list"' in captured.out
    assert '"delete"' in captured.out
