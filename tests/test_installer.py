from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from keepygaga import installer
from keepygaga.host_common import HostSetupError, HostSetupPartialError


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/Users/example/.local/share/uv/tools/keepygaga", "uv-tool"),
        ("/Users/example/.local/pipx/venvs/keepygaga", "pipx"),
        ("/Users/example/project/.venv", "python-package"),
    ],
)
def test_install_channel_uses_the_active_environment(
    prefix: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installer.sys, "prefix", prefix)
    monkeypatch.setattr(installer.sys, "executable", f"{prefix}/bin/python")

    assert installer._channel() == expected


def test_install_uses_selected_hosts_and_records_observational_state(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "agents-memory"
    state = tmp_path / "install-state.json"
    calls: list[str] = []
    monkeypatch.setattr(installer, "state_path", lambda *_args: state)
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda host, *_args: calls.append(host) or {"status": "no_op"},
    )

    result = installer.install(config_path, memory_root, ["codex", "codex"])

    assert result["status"] == "applied"
    assert calls == ["codex"]
    assert state.exists()
    assert memory_root.joinpath("profile.md").exists()
    generated = config_path.read_text(encoding="utf-8")
    assert "[memory.limits]" in generated
    assert "fixed_page_chars = 2000" in generated
    assert "lowering never deletes existing pages" in generated


def test_uninstall_preserves_config_and_memory(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "agents-memory"
    state = tmp_path / "install-state.json"
    monkeypatch.setattr(installer, "state_path", lambda *_args: state)
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: {"status": "applied"},
    )
    installer.install(config_path, memory_root, ["codex"])

    result = installer.uninstall(config_path, ["codex"])

    assert result["status"] == "applied"
    assert config_path.exists()
    assert memory_root.exists()


def test_install_does_not_overwrite_unconfigured_existing_toml(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    original = b'[other]\nvalue = "preserve"\n'
    config.write_bytes(original)

    try:
        installer.ensure_config(config, tmp_path / "memory")
    except HostSetupError as exc:
        assert "does not define memory.root" in str(exc)
    else:
        raise AssertionError("expected fail-closed existing-config error")

    assert config.read_bytes() == original


def test_install_records_each_success_before_later_host_failure(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config.toml"
    memory = tmp_path / "memory"

    def host_result(host, *_args):
        if host == "claude-code":
            raise HostSetupError("simulated failure")
        return {"status": "applied"}

    monkeypatch.setattr(installer, "_call_host", host_result)

    try:
        installer.install(config, memory, ["codex", "claude-code"])
    except HostSetupPartialError as exc:
        hosts = exc.components["hosts"]
        assert isinstance(hosts, dict)
        assert "codex" in hosts
    else:
        raise AssertionError("expected later host failure")

    state = installer._load_state(config)
    assert set(state["hosts"]) == {"codex"}


def test_explicit_configs_have_independent_state_paths(tmp_path: Path) -> None:
    first = tmp_path / "one" / "config.toml"
    second = tmp_path / "two" / "config.toml"

    assert installer.state_path(first) != installer.state_path(second)


def test_install_records_grok_rules_fallback(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: {"status": "no_op"},
    )

    installer.install(config_path, memory_root, ["grok"])

    state = json.loads(installer.state_path(config_path).read_text(encoding="utf-8"))
    assert state["hosts"]["grok"]["hooks_enabled"] is False
    assert state["hosts"]["grok"]["hook_protocol_version"] is None


def test_status_plan_distinguishes_update_from_initialization(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    config_path = tmp_path / "config.toml"

    update = installer.status(
        config_path,
        latest_version="v99.0.0",
        host="codex",
    )
    current = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert update["lifecycle"]["action"] == "update"  # type: ignore[index]
    assert current["lifecycle"]["action"] == "initialize"  # type: ignore[index]


def test_status_plan_distinguishes_activate_repair_and_no_op(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: {"status": "no_op"},
    )
    installer.install(config_path, memory_root, ["codex"])

    monkeypatch.setattr(installer, "_contract_status", lambda _host: "current")
    activate = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="claude-code",
    )
    no_op = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )
    monkeypatch.setattr(installer, "_contract_status", lambda _host: "drift")
    repair = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert activate["lifecycle"]["action"] == "activate"  # type: ignore[index]
    assert no_op["lifecycle"]["action"] == "no_op"  # type: ignore[index]
    assert repair["lifecycle"]["action"] == "repair"  # type: ignore[index]


def test_status_plan_refuses_unknown_update_owner(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "python-package")

    result = installer.status(
        tmp_path / "config.toml",
        latest_version="99.0.0",
        host="codex",
    )

    assert result["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


def test_status_plan_never_downgrades_or_switches_a_specific_owner(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer, "__version__", "1.0.0")
    newer = installer.status(
        tmp_path / "config.toml",
        latest_version="0.9.0",
        host="codex",
    )
    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": "pipx"},
    )
    mismatch = installer.status(
        tmp_path / "config.toml",
        latest_version="1.0.0",
        host="codex",
    )

    assert newer["lifecycle"]["action"] == "manual_review"  # type: ignore[index]
    assert mismatch["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


def test_status_plan_repairs_legacy_generic_channel_state(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: {"status": "no_op"},
    )
    installer.install(config_path, memory_root, ["codex"])
    state = installer._load_state(config_path)
    state["install_channel"] = "python-package"
    installer.state_path(config_path).write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(installer, "_contract_status", lambda _host: "current")

    result = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert result["install_channel"] == "uv-tool"
    assert result["recorded_install_channel"] == "python-package"
    assert result["lifecycle"]["action"] == "repair"  # type: ignore[index]


def test_status_plan_rejects_invalid_or_incomplete_request(tmp_path: Path) -> None:
    with pytest.raises(HostSetupError, match="requires --latest-version and --host"):
        installer.status(tmp_path / "config.toml", latest_version="0.7.3")
    with pytest.raises(HostSetupError, match="stable release tag"):
        installer.status(
            tmp_path / "config.toml",
            latest_version="latest",
            host="codex",
        )


def test_upgrade_without_recorded_hosts_skips_repair(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda command, **_kwargs: (
            calls.append(command)
            or type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ),
    )

    result = installer.upgrade(tmp_path / "config.toml", apply=True)

    assert result["status"] == "applied"
    assert result["repair"] == "skipped"
    assert len(calls) == 1


def test_upgrade_repairs_recorded_grok_host(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": "uv-tool", "hosts": {"grok": {}}},
    )
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda command, **_kwargs: (
            calls.append(command) or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )

    result = installer.upgrade(config_path, apply=True)

    assert result["status"] == "applied"
    assert calls == [
        ["/bin/uv", "tool", "upgrade", "keepygaga"],
        [
            "/bin/keepygaga",
            "--config",
            str(config_path.resolve()),
            "repair",
            "--yes",
        ],
    ]


def test_upgrade_timeout_becomes_host_setup_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("uv", 300)
        ),
    )

    try:
        installer.upgrade(tmp_path / "config.toml", apply=True)
    except HostSetupError as exc:
        assert "could not be started" in str(exc)
    else:
        raise AssertionError("expected structured upgrade error")


def test_upgrade_refuses_unknown_or_mismatched_install_owner(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "python-package")
    with pytest.raises(HostSetupError, match="automatic upgrade"):
        installer.upgrade(tmp_path / "config.toml", apply=True)

    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": "pipx"},
    )
    with pytest.raises(HostSetupError, match="differs from recorded channel"):
        installer.upgrade(tmp_path / "config.toml", apply=True)


def test_memory_init_partial_commit_preserves_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        installer,
        "initialize_memory_tree",
        lambda *_args: {
            "status": "partial_commit",
            "created_pages": ["profile.md"],
        },
    )

    try:
        installer.install(tmp_path / "config.toml", tmp_path / "memory", ["codex"])
    except HostSetupPartialError as exc:
        assert exc.components["memory"] == {
            "status": "partial_commit",
            "created_pages": ["profile.md"],
        }
    else:
        raise AssertionError("expected partial memory evidence")


def test_first_host_failure_reports_created_config_and_memory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: (_ for _ in ()).throw(HostSetupError("host preflight failed")),
    )

    try:
        installer.install(tmp_path / "config.toml", tmp_path / "memory", ["codex"])
    except HostSetupPartialError as exc:
        assert exc.components["config"]["status"] == "applied"  # type: ignore[index]
        assert exc.components["memory"]["status"] == "applied"  # type: ignore[index]
    else:
        raise AssertionError("expected partial initialization evidence")


def test_first_host_partial_failure_reports_created_config_and_memory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        installer,
        "_call_host",
        lambda *_args: (_ for _ in ()).throw(
            HostSetupPartialError(
                "host partially applied", {"mcp": {"status": "applied"}}
            )
        ),
    )

    try:
        installer.install(tmp_path / "config.toml", tmp_path / "memory", ["codex"])
    except HostSetupPartialError as exc:
        assert exc.components["config"]["status"] == "applied"  # type: ignore[index]
        assert exc.components["memory"]["status"] == "applied"  # type: ignore[index]
        assert exc.components["hosts"]["codex"]["mcp"] == {  # type: ignore[index]
            "status": "applied"
        }
    else:
        raise AssertionError("expected complete partial evidence")


def test_upgrade_repair_failure_reports_partial_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": "uv-tool", "hosts": {"codex": {}}},
    )
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    results = iter((0, 1))
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"returncode": next(results), "stdout": "", "stderr": "repair failed"},
        )(),
    )

    try:
        installer.upgrade(tmp_path / "config.toml", apply=True)
    except HostSetupPartialError as exc:
        assert exc.components["upgrade"]["status"] == "applied"  # type: ignore[index]
        assert exc.components["repair"]["status"] == "failed"  # type: ignore[index]
    else:
        raise AssertionError("expected partial upgrade evidence")


def test_upgrade_failure_with_missing_streams_stays_structured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv", "tool", "upgrade", "keepygaga"], 1, None, None
        ),
    )

    try:
        installer.upgrade(tmp_path / "config.toml", apply=True)
    except HostSetupError as exc:
        assert "unknown uv error" in str(exc)
    else:
        raise AssertionError("expected structured upgrade error")
