import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from keepygaga import cli, host_adapters, installer
from keepygaga.host_common import HostSetupPartialError


def test_no_subcommand_prints_help(capsys) -> None:
    assert cli.main([]) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "doctor" in captured.out
    assert "memory" in captured.out


def test_unknown_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli.main(["unknown"])


def test_route_command_does_not_load_memory_or_host_implementations() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; import keepygaga.cli; "
                "keepygaga.cli.main(['hook', 'run', 'route', '--host', 'codex', "
                "'--event', 'UserPromptSubmit']); "
                "assert 'keepygaga.host_setup' not in sys.modules; "
                "assert 'keepygaga.host_adapters' not in sys.modules; "
                "assert 'keepygaga.memory_store' not in sys.modules; "
                "assert 'pydantic' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        input="{}",
    )
    assert probe.returncode == 0, probe.stderr


def test_non_hermes_adapters_do_not_load_yaml_runtime() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; import keepygaga.host_adapters; "
                "assert not any(name.startswith('ruamel.yaml') for name in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["host", "setup", "codex", "--host-home", "/tmp/host"],
        ["host", "setup", "claude-code", "--codex-home", "/tmp/codex"],
        ["host", "setup", "hermes", "--grok-binary", "/tmp/grok"],
        ["host", "uninstall", "codex", "--host-home", "/tmp/host"],
        ["host", "uninstall", "claude-code", "--codex-home", "/tmp/codex"],
        ["host", "uninstall", "hermes", "--grok-binary", "/tmp/grok"],
    ],
)
def test_host_setup_rejects_options_for_another_host(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["host", "setup", "--host-home", "/tmp/host", "workbuddy"],
        ["host", "setup", "--codex-home", "/tmp/codex", "codex"],
        ["host", "setup", "--grok-binary", "/tmp/grok", "grok"],
        ["host", "uninstall", "--host-home", "/tmp/host", "workbuddy"],
        ["host", "uninstall", "--codex-home", "/tmp/codex", "codex"],
        ["host", "uninstall", "--grok-binary", "/tmp/grok", "grok"],
    ],
)
def test_host_setup_accepts_options_before_host(arguments: list[str]) -> None:
    parser = cli._parser()
    args = parser.parse_args(arguments)
    cli._validate_host_options(args, parser)


def test_options_before_host_reach_selected_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")
    received: dict[str, object] = {}

    def fake_setup(_config_path, _config, **options) -> dict[str, object]:
        received.update(options)
        return {"status": "no_op", "host": "workbuddy"}

    monkeypatch.setattr(host_adapters, "setup_workbuddy_host", fake_setup)
    host_home = tmp_path / ".workbuddy"
    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "host",
                "setup",
                "--host-home",
                str(host_home),
                "workbuddy",
            ]
        )
        == 0
    )
    assert received == {
        "host_home": host_home,
    }
    assert json.loads(capsys.readouterr().out)["status"] == "no_op"


def test_host_setup_partial_error_is_rendered_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")

    def fail_setup(*_args, **_kwargs) -> dict[str, object]:
        raise HostSetupPartialError(
            "simulated partial write", {"mcp": {"status": "applied"}}
        )

    monkeypatch.setattr(host_adapters, "setup_workbuddy_host", fail_setup)

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "host",
                "setup",
                "workbuddy",
                "--host-home",
                str(tmp_path / ".workbuddy"),
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "partial_commit",
        "message": "simulated partial write",
        "components": {"mcp": {"status": "applied"}},
    }


def test_interactive_install_prompts_for_existing_memory_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "vault" / "agents-memory"
    received: dict[str, object] = {}

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: str(memory_root))
    monkeypatch.setattr(
        installer,
        "install",
        lambda config, root, hosts: (
            received.update(config=config, root=root, hosts=hosts)
            or {"status": "no_op"}
        ),
    )

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "install",
                "--host",
                "codex",
            ]
        )
        == 0
    )
    assert received == {
        "config": config_path.resolve(),
        "root": memory_root.resolve(),
        "hosts": ["codex"],
    }


def test_install_reuses_configured_memory_root_for_a_new_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    memory_root = tmp_path / "vault" / "agents-memory"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(
        installer,
        "install",
        lambda config, root, hosts: (
            received.update(config=config, root=root, hosts=hosts)
            or {"status": "no_op"}
        ),
    )

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "install",
                "--yes",
                "--host",
                "claude-code",
            ]
        )
        == 0
    )
    assert received == {
        "config": config_path.resolve(),
        "root": memory_root.resolve(),
        "hosts": ["claude-code"],
    }


def test_status_forwards_release_and_current_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    received: dict[str, object] = {}

    def fake_status(config, **options) -> dict[str, object]:
        received.update(config=config, **options)
        return {"status": "ok"}

    monkeypatch.setattr(installer, "status", fake_status)

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "status",
                "--latest-version",
                "v0.7.3",
                "--host",
                "codex",
            ]
        )
        == 0
    )
    assert received == {
        "config": config_path.resolve(),
        "latest_version": "v0.7.3",
        "host": "codex",
    }
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}


def test_noninteractive_install_validates_yes_before_reading_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("not toml [", encoding="utf-8")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "--config",
                str(config_path),
                "install",
                "--host",
                "codex",
            ]
        )

    assert exc_info.value.code == 2


def test_install_rejects_explicit_root_different_from_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    configured_root = tmp_path / "configured-memory"
    requested_root = tmp_path / "different-memory"
    config_path.write_text(
        f'[memory]\nroot = "{configured_root.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "install",
                "--yes",
                "--host",
                "codex",
                "--memory-root",
                str(requested_root),
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid_source"
    assert "differs from requested" in payload["message"]
    assert not requested_root.exists()


def test_host_setup_dispatches_antigravity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")
    host_home = tmp_path / ".gemini"
    called: dict[str, object] = {}

    def fake_setup(config_path: Path, config, **options) -> dict[str, object]:
        del config
        called.update({"config_path": config_path, **options})
        return {"status": "no_op", "host": "antigravity"}

    monkeypatch.setattr(host_adapters, "setup_antigravity_host", fake_setup)

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "host",
                "setup",
                "antigravity",
                "--host-home",
                str(host_home),
            ]
        )
        == 0
    )
    assert called["config_path"] == config_path.resolve()
    assert called["host_home"] == host_home
    assert '"host": "antigravity"' in capsys.readouterr().out


def test_host_uninstall_dispatches_workbuddy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("", encoding="utf-8")
    host_home = tmp_path / ".workbuddy"
    received: dict[str, object] = {}

    def fake_uninstall(config_path: Path, config, **options) -> dict[str, object]:
        del config
        received.update({"config_path": config_path, **options})
        return {"status": "no_op", "host": "workbuddy"}

    monkeypatch.setattr(host_adapters, "uninstall_workbuddy_host", fake_uninstall)

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "host",
                "uninstall",
                "--host-home",
                str(host_home),
                "workbuddy",
            ]
        )
        == 0
    )
    assert received["config_path"] == config_path.resolve()
    assert received["host_home"] == host_home
    assert json.loads(capsys.readouterr().out)["status"] == "no_op"


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


def test_hook_uses_encoded_absolute_config_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config_path = tmp_path / "配置 with spaces" / "keepygaga.toml"
    memory_root = tmp_path / "memory"
    config_path.parent.mkdir()
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n',
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config_path), "memory", "init"]) == 0
    capsys.readouterr()
    token = base64.urlsafe_b64encode(str(config_path).encode("utf-8")).decode("ascii")
    monkeypatch.setattr(sys.stdin, "read", lambda: '{"session_id":"encoded-config"}')

    result = cli.main(
        [
            "hook",
            "run",
            "context",
            "--host",
            "codex",
            "--event",
            "SessionStart",
            "--config-base64",
            token,
        ]
    )

    assert result == 0
    assert "<keepygaga-bootstrap>" in capsys.readouterr().out


@pytest.mark.parametrize("token", ["not+urlsafe", "cmVsYXRpdmUudG9tbA=="])
def test_hook_rejects_invalid_encoded_config_path(token: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(
            [
                "hook",
                "run",
                "context",
                "--host",
                "codex",
                "--event",
                "SessionStart",
                "--config-base64",
                token,
            ]
        )


def test_memory_init_reports_permission_error_as_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
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
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text("not toml [", encoding="utf-8")

    assert cli.main(["--config", str(config_path), "memory", "init"]) == 1
    output = capsys.readouterr().out
    assert '"status": "invalid_source"' in output
    assert "configuration could not be loaded" in output


def test_memory_init_rejects_malformed_existing_pages(
    tmp_path: Path,
    capsys,
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
    assert not any(
        (memory_root / directory).exists()
        for directory in ("topics", "areas", "people")
    )


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
