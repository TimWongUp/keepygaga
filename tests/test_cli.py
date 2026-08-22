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
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0
    assert (memory_root / "profile.md").is_file()
    assert (memory_root / "preferences.md").is_file()


def test_memory_init_is_successful_when_tree_is_already_initialized(
    tmp_path: Path, capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0
    assert '"status": "no_op"' in capsys.readouterr().out


def test_cli_uses_environment_config_path(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KEEPYGAGA_CONFIG", str(config_path))

    assert cli.main(["memory", "init"]) == 0
    assert (memory_root / "profile.md").is_file()


def test_memory_init_reports_permission_error_as_json(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    original_mkdir = Path.mkdir

    def deny_root(path: Path, *args, **kwargs) -> None:
        if path == memory_root:
            raise PermissionError("simulated permission failure")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny_root)

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    output = capsys.readouterr().out
    assert '"status": "permission_denied"' in output
    assert "simulated permission failure" in output


def test_memory_init_refuses_unconfigured_root(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    captured = capsys.readouterr()
    assert '"status": "invalid_source"' in captured.out


def test_memory_init_reports_invalid_config_as_json(
    tmp_path: Path, capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("not toml [", encoding="utf-8")

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    output = capsys.readouterr().out
    assert '"status": "invalid_source"' in output
    assert "configuration could not be loaded" in output


def test_memory_init_rejects_malformed_existing_pages(
    tmp_path: Path, capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "profile.md").write_text("malformed\n", encoding="utf-8")
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    output = capsys.readouterr().out
    assert '"status": "invalid_source"' in output
    assert '"status": "no_op"' not in output
    assert not (memory_root / "preferences.md").exists()
    assert not (memory_root / ".keepygaga.lock").exists()
    assert not any((memory_root / directory).exists() for directory in ("topics", "areas", "people"))


def test_doctor_prints_json_and_reports_eight_tools(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0

    assert cli.main(["--config", str(config_path), "doctor"]) == 0
    captured = capsys.readouterr()
    assert '"status": "ok"' in captured.out
    assert '"tools"' in captured.out
    assert '"list"' in captured.out
    assert '"delete"' in captured.out
