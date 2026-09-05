from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from keepygaga import host_adapters, installer, launchers
from keepygaga.host_common import HostSetupError, HostSetupPartialError


@pytest.fixture
def uv_tool_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "uv" / "tools"
    monkeypatch.setattr(installer, "_uv_tool_root", lambda: root)
    return root


def test_install_channel_uses_the_active_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "uv" / "tools" / "keepygaga"
    prefix.mkdir(parents=True)
    prefix.joinpath("uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "keepygaga" }]\n', encoding="utf-8"
    )
    monkeypatch.setattr(installer.sys, "prefix", str(prefix))
    monkeypatch.setattr(installer.sys, "executable", str(prefix / "bin" / "python"))

    assert installer._channel() == "uv-tool"


def test_install_channel_does_not_trust_a_uv_shaped_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "uv" / "tools" / "keepygaga"
    monkeypatch.setattr(installer.sys, "prefix", str(prefix))
    monkeypatch.setattr(installer.sys, "executable", str(prefix / "bin" / "python"))

    assert installer._channel() == "python-package"


def test_install_channel_recognizes_pipx_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "/Users/example/.local/pipx/venvs/keepygaga"
    monkeypatch.setattr(installer.sys, "prefix", prefix)
    monkeypatch.setattr(installer.sys, "executable", f"{prefix}/bin/python")

    assert installer._channel() == "pipx"


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


@pytest.mark.parametrize("hosts", [["codex"], {"unknown": {}}, {"codex": []}])
def test_load_state_rejects_malformed_hosts(tmp_path: Path, hosts: object) -> None:
    config_path = tmp_path / "config.toml"
    installer.state_path(config_path).write_text(
        json.dumps(
            {
                "schema_version": installer.INSTALLER_SCHEMA_VERSION,
                "hosts": hosts,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HostSetupError, match="invalid hosts"):
        installer._load_state(config_path)


@pytest.mark.parametrize("generation", [None, ""])
def test_load_state_rejects_invalid_upgrade_generation(
    tmp_path: Path, generation: object
) -> None:
    config_path = tmp_path / "config.toml"
    installer.state_path(config_path).write_text(
        json.dumps(
            {
                "schema_version": installer.INSTALLER_SCHEMA_VERSION,
                "installed_version": "0.8.0",
                "hosts": {},
                "upgrade_generation": generation,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HostSetupError, match="install state is invalid"):
        installer._load_state(config_path)


def test_install_does_not_overwrite_a_concurrent_sibling_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    state = installer.state_path(config_path)
    initial = {
        "schema_version": installer.INSTALLER_SCHEMA_VERSION,
        "install_channel": "python-package",
        "hosts": {},
    }
    state.write_text(json.dumps(initial), encoding="utf-8")

    def record_sibling(*_args):
        concurrent = {**initial, "hosts": {"claude-code": {}}}
        state.write_text(json.dumps(concurrent), encoding="utf-8")
        return {"status": "no_op"}

    monkeypatch.setattr(installer, "_call_host", record_sibling)

    with pytest.raises(HostSetupPartialError, match="state could not be updated"):
        installer.install(config_path, memory_root, ["codex"])

    assert json.loads(state.read_text(encoding="utf-8"))["hosts"] == {"claude-code": {}}


def test_install_restarts_when_upgrade_generation_is_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    installer.state_path(config_path).write_text(
        json.dumps(
            {
                "schema_version": installer.INSTALLER_SCHEMA_VERSION,
                "installed_version": "0.8.0",
                "install_channel": "uv-tool",
                "hosts": {},
                "upgrade_generation": "generation",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(installer, "_call_host", lambda *_args: {"status": "no_op"})
    installer.install(config_path, tmp_path / "memory", ["codex"])
    state = installer._load_state(config_path)
    assert state["upgrade_generation"] == "generation"

    monkeypatch.setattr(installer, "__version__", "0.9.0")
    installer.install(config_path, tmp_path / "memory", ["claude-code"])
    state = installer._load_state(config_path)
    assert state["installed_version"] == "0.9.0"
    assert state["upgrade_generation"] == "generation"

    monkeypatch.setattr(installer, "__version__", "0.7.3")
    with pytest.raises(HostSetupError, match="runtime changed"):
        installer.install(config_path, tmp_path / "memory", ["grok"])


def test_state_writers_serialize_the_final_replace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    ready = Barrier(2)

    def write(host: str) -> str:
        ready.wait()
        try:
            installer._write_state(
                config_path,
                tmp_path / "memory",
                {host: {}},
                expected_original=None,
            )
        except HostSetupError:
            return "conflict"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("codex", "claude-code")))

    assert sorted(results) == ["applied", "conflict"]


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
    tmp_path: Path, monkeypatch, uv_tool_root: Path
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
    assert update["lifecycle"]["tool_root"] == str(uv_tool_root)  # type: ignore[index]
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
    monkeypatch.setattr(installer, "_wiring_status", lambda *_args: "current")
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
    monkeypatch.setattr(installer, "_wiring_status", lambda *_args: "current")

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


def test_planned_status_reads_only_the_current_host_contract(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer, "_call_host", lambda *_args: {"status": "no_op"})
    installer.install(config_path, memory_root, ["codex", "claude-code"])
    checked: list[str] = []
    monkeypatch.setattr(installer, "_wiring_status", lambda *_args: "current")
    monkeypatch.setattr(
        installer,
        "_contract_status",
        lambda selected: checked.append(selected) or "current",
    )

    result = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert set(result["hosts"]) == {"codex"}  # type: ignore[arg-type]
    assert set(checked) == {"codex"}


@pytest.mark.parametrize("channel", ["python-package", "pipx"])
def test_status_plan_refuses_unknown_update_owner(
    tmp_path: Path, monkeypatch, channel: str
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: channel)

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


@pytest.mark.parametrize("live_channel", ["uv-tool", "python-package"])
def test_status_plan_refuses_generic_channel_even_at_same_version(
    tmp_path: Path, monkeypatch, live_channel: str
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: live_channel)
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
    monkeypatch.setattr(installer, "_wiring_status", lambda *_args: "current")

    result = installer.status(
        config_path,
        latest_version=installer.__version__,
        host="codex",
    )

    assert result["install_channel"] == live_channel
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


@pytest.mark.parametrize("latest_version", [installer.__version__, "99.0.0"])
def test_status_plan_sends_contract_conflict_to_manual_review(
    tmp_path: Path, monkeypatch, latest_version: str
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer, "_call_host", lambda *_args: {"status": "no_op"})
    installer.install(config_path, memory_root, ["codex"])
    monkeypatch.setattr(installer, "_contract_status", lambda _host: "conflict")

    result = installer.status(
        config_path,
        latest_version=latest_version,
        host="codex",
    )

    assert result["lifecycle"]["action"] == "manual_review"  # type: ignore[index]


def test_status_plan_checks_contract_conflict_before_unrecorded_activation(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer, "_call_host", lambda *_args: {"status": "no_op"})
    installer.install(config_path, memory_root, ["codex"])
    state = installer._load_state(config_path)
    state["hosts"] = {}
    installer.state_path(config_path).write_text(json.dumps(state), encoding="utf-8")
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
    tmp_path: Path, monkeypatch, uv_tool_root: Path
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
    state = installer._load_state(tmp_path / "config.toml")
    assert state["installed_version"] == installer.package_version("keepygaga")
    assert isinstance(state["upgrade_generation"], str)


def test_upgrade_reports_concurrent_state_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uv_tool_root: Path
) -> None:
    config_path = tmp_path / "config.toml"
    state = installer.state_path(config_path)
    initial = {
        "schema_version": installer.INSTALLER_SCHEMA_VERSION,
        "install_channel": "uv-tool",
        "hosts": {},
    }
    state.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")

    def change_state(command, **_kwargs):
        concurrent = {**initial, "hosts": {"codex": {}}}
        state.write_text(json.dumps(concurrent), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(installer, "run_captured", change_state)

    with pytest.raises(HostSetupPartialError, match="could not be verified") as caught:
        installer.upgrade(config_path, apply=True)

    assert caught.value.components["upgrade"]["status"] == "applied"  # type: ignore[index]
    assert json.loads(state.read_text(encoding="utf-8"))["hosts"] == {"codex": {}}


def test_upgrade_repairs_recorded_grok_host(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(
        installer,
        "_read_state_snapshot",
        lambda _path: (
            {"install_channel": "uv-tool", "hosts": {"grok": {}}},
            None,
        ),
    )
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        installer,
        "resolve_active_launcher",
        lambda _name: Path("/active/bin/keepygaga"),
    )
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    tool_root = tmp_path / "uv" / "tools"
    monkeypatch.setattr(installer, "_uv_tool_root", lambda: tool_root)
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda command, **kwargs: (
            calls.append((command, kwargs))
            or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )

    result = installer.upgrade(config_path, apply=True)

    assert result["status"] == "applied"
    assert [command for command, _kwargs in calls] == [
        ["/bin/uv", "tool", "upgrade", "keepygaga"],
        [
            str(Path("/active/bin/keepygaga")),
            "--config",
            str(config_path.resolve()),
            "repair",
            "--yes",
        ],
    ]
    assert calls[0][1]["env"]["UV_TOOL_DIR"] == str(tool_root)  # type: ignore[index]


def test_upgrade_timeout_becomes_host_setup_error(
    tmp_path: Path, monkeypatch, uv_tool_root: Path
) -> None:
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

    monkeypatch.setattr(installer, "_channel", lambda: "pipx")
    with pytest.raises(HostSetupError, match="automatic upgrade"):
        installer.upgrade(tmp_path / "config.toml", apply=True)

    monkeypatch.setattr(installer, "_channel", lambda: "python-package")
    monkeypatch.setattr(
        installer,
        "_read_state_snapshot",
        lambda _path: ({"install_channel": "pipx"}, None),
    )
    with pytest.raises(HostSetupError, match="differs from or is not supported"):
        installer.upgrade(tmp_path / "config.toml", apply=True)


@pytest.mark.parametrize("recorded", ["mystery", [], {}, "python-package"])
def test_upgrade_refuses_invalid_recorded_owner(
    tmp_path: Path, monkeypatch, uv_tool_root: Path, recorded: object
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_read_state_snapshot",
        lambda _path: ({"install_channel": recorded}, None),
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
    tmp_path: Path, monkeypatch, uv_tool_root: Path
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_read_state_snapshot",
        lambda _path: (
            {"install_channel": "uv-tool", "hosts": {"codex": {}}},
            None,
        ),
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


def test_upgrade_missing_active_launcher_preserves_partial_evidence(
    tmp_path: Path, monkeypatch, uv_tool_root: Path
) -> None:
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    monkeypatch.setattr(
        installer,
        "_read_state_snapshot",
        lambda _path: (
            {"install_channel": "uv-tool", "hosts": {"codex": {}}},
            None,
        ),
    )
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        installer,
        "resolve_active_launcher",
        lambda _name: (_ for _ in ()).throw(RuntimeError("launcher missing")),
    )
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    with pytest.raises(HostSetupPartialError) as caught:
        installer.upgrade(tmp_path / "config.toml", apply=True)

    assert caught.value.components["upgrade"]["status"] == "applied"  # type: ignore[index]
    assert caught.value.components["repair"]["status"] == "failed"  # type: ignore[index]


def test_upgrade_failure_with_missing_streams_stays_structured(
    tmp_path: Path, monkeypatch, uv_tool_root: Path
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


def test_status_detects_live_mcp_and_hook_drift_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uv_tool_root: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(installer, "_channel", lambda: "uv-tool")
    config_path = tmp_path / "config.toml"
    memory_root = tmp_path / "memory"
    installer.install(config_path, memory_root, ["workbuddy"])
    home = tmp_path / ".workbuddy"
    mcp_path = home / "mcp.json"
    hooks_path = home / "settings.json"
    original_mcp = mcp_path.read_bytes()
    original_hooks = hooks_path.read_bytes()
    state_path = installer.state_path(config_path)
    original_state = state_path.read_bytes()

    current = installer.status(
        config_path, latest_version=installer.__version__, host="workbuddy"
    )
    assert current["lifecycle"]["action"] == "no_op"  # type: ignore[index]
    assert current["hosts"]["workbuddy"]["wiring"] == "current"  # type: ignore[index]

    mcp_path.unlink()
    missing = installer.status(
        config_path, latest_version=installer.__version__, host="workbuddy"
    )
    assert missing["lifecycle"]["action"] == "repair"  # type: ignore[index]
    assert not mcp_path.exists()
    mcp_path.write_bytes(original_mcp)

    hooks = json.loads(original_hooks)
    hooks["hooks"].pop("UserPromptSubmit")
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")
    drift = installer.status(
        config_path, latest_version=installer.__version__, host="workbuddy"
    )
    assert drift["lifecycle"]["action"] == "repair"  # type: ignore[index]
    assert json.loads(hooks_path.read_bytes()) == hooks

    hooks_path.write_text("invalid JSON", encoding="utf-8")
    for latest_version in (installer.__version__, "99.0.0"):
        conflict = installer.status(
            config_path, latest_version=latest_version, host="workbuddy"
        )
        assert conflict["lifecycle"]["action"] == "manual_review"  # type: ignore[index]
    assert hooks_path.read_text(encoding="utf-8") == "invalid JSON"
    assert state_path.read_bytes() == original_state
    assert mcp_path.read_bytes() == original_mcp
