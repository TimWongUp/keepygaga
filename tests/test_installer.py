from __future__ import annotations

import json
import subprocess
from pathlib import Path

from keepygaga import installer
from keepygaga.host_common import HostSetupError, HostSetupPartialError


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


def test_upgrade_without_recorded_hosts_skips_repair(
    tmp_path: Path, monkeypatch
) -> None:
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
