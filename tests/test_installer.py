from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from keepygaga import host_adapters, installer, launchers
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


def test_active_launcher_stays_with_the_running_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts = tmp_path / ("Scripts" if launchers.os.name == "nt" else "bin")
    scripts.mkdir()
    launcher = scripts / ("keepygaga.exe" if launchers.os.name == "nt" else "keepygaga")
    launcher.write_text("launcher", encoding="utf-8")
    launcher.chmod(0o700)
    monkeypatch.setattr(launchers.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(launchers.shutil, "which", lambda _name: "/wrong/keepygaga")

    assert launchers.resolve_active_launcher("keepygaga") == launcher.resolve()


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
    assert state["hosts"]["grok"]["reconciled_version"] == installer.__version__
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
    state = installer._load_state(config_path)
    state["hosts"]["codex"]["hook_protocol_version"] = 0
    installer.state_path(config_path).write_text(json.dumps(state), encoding="utf-8")
    stale_projection = installer.status(
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
    assert stale_projection["lifecycle"]["action"] == "repair"  # type: ignore[index]
    assert repair["lifecycle"]["action"] == "repair"  # type: ignore[index]


def test_status_plan_keeps_unreconciled_sibling_stale(
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
    monkeypatch.setattr(installer, "__version__", "0.7.3")
    installer.install(config_path, memory_root, ["codex", "claude-code"])

    monkeypatch.setattr(installer, "__version__", "0.8.0")
    installer.install(config_path, memory_root, ["codex"])
    monkeypatch.setattr(installer, "_contract_status", lambda _host: "current")

    current = installer.status(
        config_path,
        latest_version="0.8.0",
        host="codex",
    )
    sibling = installer.status(
        config_path,
        latest_version="0.8.0",
        host="claude-code",
    )
    state = installer._load_state(config_path)

    assert current["lifecycle"]["action"] == "no_op"  # type: ignore[index]
    assert sibling["lifecycle"]["action"] == "repair"  # type: ignore[index]
    assert state["hosts"]["codex"]["reconciled_version"] == "0.8.0"
    assert state["hosts"]["claude-code"]["reconciled_version"] == "0.7.3"


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


def test_status_plan_refuses_legacy_generic_channel_state(
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
    assert result["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


@pytest.mark.parametrize("recorded", ["mystery", [], {}])
def test_status_plan_refuses_invalid_recorded_owner(
    tmp_path: Path, monkeypatch, recorded: object
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": recorded},
    )

    result = installer.status(
        tmp_path / "config.toml",
        latest_version="99.0.0",
        host="codex",
    )

    assert result["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


def test_contract_status_requires_exact_canonical_block(
    tmp_path: Path, monkeypatch
) -> None:
    rules = tmp_path / "AGENTS.md"
    canonical = installer.load_canonical_contract()
    monkeypatch.setattr(installer, "_rules_path", lambda _host: rules)

    rules.write_text(canonical, encoding="utf-8")
    assert installer._contract_status("codex") == "current"

    rules.write_text(
        canonical.replace("# Keepygaga Agent Contract", "# altered"), encoding="utf-8"
    )
    assert installer._contract_status("codex") == "drift"

    rules.write_text(
        canonical.replace(
            f"KEEPYGAGA:CONTRACT:{installer.CONTRACT_VERSION}",
            "KEEPYGAGA:CONTRACT:50",
        ),
        encoding="utf-8",
    )
    assert installer._contract_status("codex") == "drift"


def test_contract_status_detects_conflicting_host_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    canonical = installer.load_canonical_contract()
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "AGENTS.override.md").write_text(canonical, encoding="utf-8")
    (codex_home / "AGENTS.md").write_text(canonical, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert installer._contract_status("codex") == "conflict"

    monkeypatch.delenv("CODEX_HOME")
    grok_home = tmp_path / ".grok"
    grok_home.mkdir()
    upper = tmp_path / "upper" / "AGENTS.md"
    title = tmp_path / "title" / "Agents.md"
    upper.parent.mkdir()
    title.parent.mkdir()
    upper.write_text(canonical, encoding="utf-8")
    title.write_text(canonical, encoding="utf-8")
    original_iterdir = Path.iterdir

    def fake_iterdir(path: Path):
        return iter((upper, title)) if path == grok_home else original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(host_adapters.os.path, "samefile", lambda *_args: False)
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda _cls: tmp_path))
    assert installer._contract_status("grok") == "conflict"


def test_status_plan_sends_contract_conflict_to_manual_review(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer, "_call_host", lambda *_args: {"status": "no_op"})
    installer.install(config_path, memory_root, ["codex"])
    monkeypatch.setattr(installer, "_contract_status", lambda _host: "conflict")

    result = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert result["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


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
    monkeypatch.setattr(
        installer,
        "resolve_active_launcher",
        lambda _name: Path("/active/bin/keepygaga"),
    )
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
            str(Path("/active/bin/keepygaga")),
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
    with pytest.raises(HostSetupError, match="differs from or is not supported"):
        installer.upgrade(tmp_path / "config.toml", apply=True)


@pytest.mark.parametrize("recorded", ["mystery", [], {}, "python-package"])
def test_upgrade_refuses_invalid_recorded_owner(
    tmp_path: Path, monkeypatch, recorded: object
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_load_state",
        lambda _path: {"install_channel": recorded},
    )

    with pytest.raises(HostSetupError, match="differs from or is not supported"):
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
    monkeypatch.setattr(
        installer,
        "resolve_active_launcher",
        lambda _name: Path("/active/bin/keepygaga"),
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
