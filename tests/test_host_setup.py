from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from keepygaga import __version__, host_common, host_setup
from keepygaga.config import KeepygagaConfig, MemoryFilesConfig
from keepygaga.host_setup import HostSetupError


def canonical() -> str:
    return (
        "<!-- KEEPYGAGA:START -->\n"
        f"<!-- KEEPYGAGA:VERSION:{__version__} -->\n"
        "# Contract\n"
        "<!-- KEEPYGAGA:END -->\n"
    )


def minimal_hook_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    (runtime / "agent_hook_runtime").mkdir(parents=True)
    (runtime / "config/hooks").mkdir(parents=True)
    (runtime / "hooks").mkdir()
    (runtime / "agent_hook_runtime/hook_config.py").write_text(
        "def merge_hook_fragment(existing, fragment):\n"
        "    return {'hooks': dict(existing.get('hooks', {}))}\n",
        encoding="utf-8",
    )
    (runtime / "config/hooks/codex.json").write_text(
        json.dumps(
            {
                "host": "codex",
                "owned_command_markers": ["context_hook.py"],
                "payload": {},
            }
        ),
        encoding="utf-8",
    )
    for name in ("context_hook.py", "memory_route_hook.py", "closeout_hook.py"):
        content = "print('{}')\n" if name == "context_hook.py" else "# fixture\n"
        (runtime / "hooks" / name).write_text(content, encoding="utf-8")
    return runtime, Path(sys.executable)


def test_canonical_contract_uses_version_only() -> None:
    contract = host_setup.load_canonical_contract()

    assert f"<!-- KEEPYGAGA:VERSION:{__version__} -->" in contract
    assert "KEEPYGAGA:HASH" not in contract
    assert "SHA256" not in contract.upper()


def test_host_setup_preserves_public_common_symbols() -> None:
    assert (
        host_setup.HOOK_MERGER_RELATIVE_PATH
        == host_common.HOOK_MERGER_RELATIVE_PATH
    )


def test_canonical_contract_carries_agent_only_memory_policy() -> None:
    contract = host_setup.load_canonical_contract()

    assert "a matching injected version makes each home page" in contract
    assert "Page paths must come from the current Route Catalog" in contract
    assert "an applied mutation's `files`" in contract
    assert "After `write_conflict`, reclassify against `latest`" in contract
    assert "Route Catalog descriptions and aliases" in contract
    assert "clear owning page" in contract
    assert "Add new Profile Facts only from the user's current explicit statements" in contract
    assert "current visible context already contains repeated direct evidence" in contract
    assert "project affiliations and project roles" in contract
    assert "at most one mutation per home page per task" in contract
    assert "ensure the Page Snapshot includes the current capacity signal" in contract
    assert "explicit current-turn user authorization" in contract
    assert "Fixed home pages cannot be renamed or deleted as pages" in contract
    assert "Core-memory links may use Obsidian wikilinks" in contract
    assert "The raw tools are exactly" not in contract
    assert "The Store rejects repeated operations" not in contract


def test_merge_appends_first_block_without_changing_existing_bytes() -> None:
    existing = "# Personal\r\nkeep this\r\n"

    merged = host_setup.merge_managed_contract(
        existing, canonical(), source="AGENTS.md"
    )

    assert merged.startswith(existing)
    assert merged == existing + "\n" + canonical()


def test_merge_replaces_block_in_place_and_preserves_outside_bytes() -> None:
    existing = (
        "before\r\n"
        "<!-- KEEPYGAGA:START -->\r\n"
        "<!-- KEEPYGAGA:VERSION:0.0.1 -->\r\n"
        "old\r\n"
        "<!-- KEEPYGAGA:END -->\r\n"
        "after\r\n"
    )

    merged = host_setup.merge_managed_contract(
        existing, canonical(), source="AGENTS.md"
    )

    assert merged == "before\r\n" + canonical() + "after\r\n"


def test_merge_replaces_exact_unmanaged_legacy_contract() -> None:
    legacy = "# Keepygaga Agent Contract\n\n- old rule\n"
    existing = f"before\n{legacy}after\n"

    merged = host_setup.merge_managed_contract(
        existing, canonical(), source="AGENTS.md", legacy=legacy
    )

    assert merged == "before\n" + canonical() + "after\n"


def test_merge_refuses_modified_unmanaged_legacy_contract() -> None:
    with pytest.raises(HostSetupError, match="modified unmanaged legacy"):
        host_setup.merge_managed_contract(
            "# Keepygaga Agent Contract\n\n- locally changed\n",
            canonical(),
            source="AGENTS.md",
            legacy="# Keepygaga Agent Contract\n\n- old rule\n",
        )


@pytest.mark.parametrize(
    "existing",
    [
        "<!-- KEEPYGAGA:START -->\nmissing end\n",
        "<!-- KEEPYGAGA:END -->\n",
        (
            "<!-- KEEPYGAGA:START -->\n"
            "<!-- KEEPYGAGA:END -->\n"
            "<!-- KEEPYGAGA:START -->\n"
            "<!-- KEEPYGAGA:END -->\n"
        ),
    ],
)
def test_merge_fails_closed_for_corrupt_or_duplicate_blocks(existing: str) -> None:
    with pytest.raises(HostSetupError):
        host_setup.merge_managed_contract(existing, canonical(), source="AGENTS.md")


def test_remove_managed_contract_strips_block_and_preserves_outside_bytes() -> None:
    existing = (
        "before\r\n"
        + canonical().replace("\n", "\r\n")
        + "after\r\n"
    )

    removed = host_setup.remove_managed_contract(existing, source="AGENTS.md")

    assert removed == "before\r\nafter\r\n"


def test_remove_managed_contract_is_noop_without_block() -> None:
    existing = "# Personal\nkeep this\n"

    assert (
        host_setup.remove_managed_contract(existing, source="AGENTS.md") == existing
    )


def test_remove_managed_contract_strips_exact_unmanaged_legacy() -> None:
    legacy = "# Keepygaga Agent Contract\n\n- old rule\n"
    existing = f"before\n{legacy}after\n"

    removed = host_setup.remove_managed_contract(
        existing, source="AGENTS.md", legacy=legacy
    )

    assert removed == "before\nafter\n"


def test_remove_managed_contract_refuses_modified_unmanaged_legacy() -> None:
    with pytest.raises(HostSetupError, match="modified unmanaged legacy"):
        host_setup.remove_managed_contract(
            "# Keepygaga Agent Contract\n\n- locally changed\n",
            source="AGENTS.md",
            legacy="# Keepygaga Agent Contract\n\n- old rule\n",
        )



def test_remove_managed_contract_preserves_leading_blank_lines() -> None:
    existing = canonical() + "\nkept\n"

    removed = host_setup.remove_managed_contract(existing, source="AGENTS.md")

    assert removed == "\nkept\n"


def test_remove_managed_contract_refuses_leftover_legacy_after_block() -> None:
    legacy = "# Keepygaga Agent Contract\n\n- old rule\n"
    existing = canonical() + legacy

    with pytest.raises(HostSetupError, match="still contains an unmanaged legacy"):
        host_setup.remove_managed_contract(
            existing, source="AGENTS.md", legacy=legacy
        )

def test_rules_use_nonempty_global_override_and_are_idempotent(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    override = codex_home / "AGENTS.override.md"
    agents.write_text("base\n", encoding="utf-8")
    override.write_text("override\n", encoding="utf-8")
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_text(canonical(), encoding="utf-8")
    legacy.write_text("# Keepygaga Agent Contract\n\n- old\n", encoding="utf-8")

    first = host_setup.reconcile_codex_rules(
        codex_home, contract_path=contract, legacy_contract_path=legacy
    )
    second = host_setup.reconcile_codex_rules(
        codex_home, contract_path=contract, legacy_contract_path=legacy
    )

    assert first["status"] == "applied"
    assert second["status"] == "no_op"
    assert first["path"] == str(override)
    assert second["path"] == str(override)
    assert agents.read_text(encoding="utf-8") == "base\n"
    assert override.read_text(encoding="utf-8").startswith("override\n")


def test_rules_preserve_crlf_bytes_and_pass_original_to_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    original = b"base\r\nkeep this\r\n"
    agents.write_bytes(original)
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")
    expected: list[object] = []
    atomic_write = host_setup._atomic_write

    def capture(
        path: Path,
        content: bytes,
        *,
        expected_original: bytes | None | object = host_setup._EXPECTED_ANY,
    ) -> tuple[str, str | None]:
        expected.append(expected_original)
        return atomic_write(path, content, expected_original=expected_original)

    monkeypatch.setattr(host_setup, "_atomic_write", capture)
    result = host_setup.reconcile_codex_rules(
        codex_home, contract_path=contract, legacy_contract_path=legacy
    )

    assert result["status"] == "applied"
    assert expected == [original]
    assert agents.read_bytes() == original + b"\n" + canonical().encode("utf-8")


def test_rules_fail_closed_when_changed_after_initial_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    original = b"base\r\n"
    concurrent = b"changed by another writer\r\n"
    agents.write_bytes(original)
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")
    atomic_write = host_setup._atomic_write

    def race(
        path: Path,
        content: bytes,
        *,
        expected_original: bytes | None | object = host_setup._EXPECTED_ANY,
    ) -> tuple[str, str | None]:
        path.write_bytes(concurrent)
        return atomic_write(path, content, expected_original=expected_original)

    monkeypatch.setattr(host_setup, "_atomic_write", race)
    with pytest.raises(HostSetupError, match="write conflict"):
        host_setup.reconcile_codex_rules(
            codex_home, contract_path=contract, legacy_contract_path=legacy
        )

    assert agents.read_bytes() == concurrent


def test_rules_fail_closed_when_empty_override_becomes_effective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    override = codex_home / "AGENTS.override.md"
    agents.write_bytes(b"base\n")
    override.write_bytes(b"\n")
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")
    select = host_setup._select_codex_rules_candidate
    calls = 0

    def race(home: Path) -> tuple[Path, bytes | None, str]:
        nonlocal calls
        result = select(home)
        calls += 1
        if calls == 1:
            override.write_bytes(b"now effective\n")
        return result

    monkeypatch.setattr(host_setup, "_select_codex_rules_candidate", race)

    with pytest.raises(HostSetupError, match="candidates changed"):
        host_setup.reconcile_codex_rules(
            codex_home, contract_path=contract, legacy_contract_path=legacy
        )

    assert agents.read_bytes() == b"base\n"
    assert override.read_bytes() == b"now effective\n"


def test_rules_fail_closed_when_inactive_base_gains_managed_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    override = codex_home / "AGENTS.override.md"
    agents.write_bytes(b"base\n")
    override.write_bytes(b"override\n")
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")
    select = host_setup._select_codex_rules_candidate
    calls = 0

    def race(home: Path) -> tuple[Path, bytes | None, str]:
        nonlocal calls
        result = select(home)
        calls += 1
        if calls == 1:
            agents.write_bytes(
                b"base\n<!-- KEEPYGAGA:START -->\nold\n<!-- KEEPYGAGA:END -->\n"
            )
        return result

    monkeypatch.setattr(host_setup, "_select_codex_rules_candidate", race)

    with pytest.raises(HostSetupError, match="stale Keepygaga managed block"):
        host_setup.reconcile_codex_rules(
            codex_home, contract_path=contract, legacy_contract_path=legacy
        )

    assert override.read_bytes() == b"override\n"


def test_rules_use_override_and_refuse_stale_base_block(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "AGENTS.md").write_bytes(
        b"base\n<!-- KEEPYGAGA:START -->\nold\n<!-- KEEPYGAGA:END -->\n"
    )
    (codex_home / "AGENTS.override.md").write_bytes(b"override\n")
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")

    with pytest.raises(HostSetupError, match="stale Keepygaga managed block"):
        host_setup.reconcile_codex_rules(
            codex_home, contract_path=contract, legacy_contract_path=legacy
        )

    assert (codex_home / "AGENTS.md").read_bytes().startswith(b"base\n")
    assert (codex_home / "AGENTS.override.md").read_bytes() == b"override\n"


def test_rules_use_base_when_override_is_empty(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    override = codex_home / "AGENTS.override.md"
    agents.write_bytes(b"base\r\n")
    override.write_bytes(b"\r\n")
    contract = tmp_path / "contract.md"
    legacy = tmp_path / "legacy.md"
    contract.write_bytes(canonical().encode("utf-8"))
    legacy.write_bytes(b"# Keepygaga Agent Contract\n\n- old\n")

    result = host_setup.reconcile_codex_rules(
        codex_home, contract_path=contract, legacy_contract_path=legacy
    )

    assert result["path"] == str(agents)
    assert agents.read_bytes() == b"base\r\n\n" + canonical().encode("utf-8")
    assert override.read_bytes() == b"\r\n"


def test_mcp_registration_skips_matching_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    config = tmp_path / "keepygaga.toml"
    python.touch()
    codex.touch()
    codex.chmod(0o755)

    payload = {
        "enabled": True,
        "transport": {
            "type": "stdio",
            "command": str(python),
            "args": ["-m", "keepygaga.server"],
            "env": {"KEEPYGAGA_CONFIG": str(config)},
            "env_vars": [],
            "cwd": None,
        },
    }
    calls: list[list[str]] = []

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    result = host_setup.reconcile_codex_mcp(
        tmp_path / ".codex", config, python=python, codex_binary=codex
    )

    assert result["status"] == "no_op"
    assert calls == [
        ["mcp", "get", "keepygaga", "--json"],
        ["mcp", "get", "keepygaga", "--json"],
    ]


def test_mcp_registration_refuses_noop_drift_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    config = tmp_path / "keepygaga.toml"
    python.touch()
    codex.touch(mode=0o755)
    calls = 0

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        payload = {
            "enabled": True,
            "transport": {
                "type": "stdio",
                "command": str(python) if calls == 1 else "/changed/python",
                "args": ["-m", "keepygaga.server"],
                "env": {"KEEPYGAGA_CONFIG": str(config)},
                "env_vars": [],
                "cwd": None,
            },
        }
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    with pytest.raises(HostSetupError, match="changed after preflight"):
        host_setup.reconcile_codex_mcp(
            tmp_path / ".codex",
            config,
            python=python,
            codex_binary=codex,
        )


def test_mcp_registration_replaces_and_verifies_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = (tmp_path / "python").resolve()
    codex = (tmp_path / "codex").resolve()
    config = (tmp_path / "keepygaga.toml").resolve()
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    codex_config = codex_home / "config.toml"
    codex_config.write_text("[mcp_servers.keepygaga]\n", encoding="utf-8")
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    calls: list[list[str]] = []

    expected = {
        "enabled": True,
        "transport": {
            "type": "stdio",
            "command": str(python),
            "args": ["-m", "keepygaga.server"],
            "env": {
                "KEEPYGAGA_CONFIG": str(config),
                "KEEP_EXISTING": "1",
            },
            "env_vars": [],
            "cwd": None,
        },
    }

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if len(calls) == 1:
            current = {
                **expected,
                "enabled": False,
                "transport": {
                    **expected["transport"],
                    "command": "/old/python",
                },
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(current), "")
        if arguments[1] == "add":
            return subprocess.CompletedProcess(arguments, 0, "Added", "")
        return subprocess.CompletedProcess(arguments, 0, json.dumps(expected), "")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    result = host_setup.reconcile_codex_mcp(
        codex_home, config, python=python, codex_binary=codex
    )

    assert result["status"] == "applied"
    assert Path(str(result["backup"])).read_text(encoding="utf-8") == (
        "[mcp_servers.keepygaga]\n"
    )
    assert calls[1][:4] == ["mcp", "add", "keepygaga", "--env"]
    assert "KEEP_EXISTING=1" in calls[1]
    assert calls[2] == ["mcp", "get", "keepygaga", "--json"]


def test_mcp_registration_reports_partial_commit_when_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    config = tmp_path / "keepygaga.toml"
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    calls = 0

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                arguments,
                1,
                "",
                "No MCP server named 'keepygaga' found.",
            )
        if calls == 2:
            return subprocess.CompletedProcess(arguments, 0, "Added", "")
        return subprocess.CompletedProcess(arguments, 0, "not json", "")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    with pytest.raises(host_setup.HostSetupPartialError) as error:
        host_setup.reconcile_codex_mcp(
            tmp_path / ".codex", config, python=python, codex_binary=codex
        )

    assert error.value.components["mcp"] == {
        "status": "applied",
        "key": "keepygaga",
        "verified": False,
        "backup": None,
        "recovery": {
            "action": "remove_new_registration",
            "status": "applied",
        },
    }


def test_mcp_registration_refuses_unreadable_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    calls: list[list[str]] = []

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 2, "", "permission denied")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    with pytest.raises(HostSetupError, match="could not be read"):
        host_setup.reconcile_codex_mcp(
            tmp_path / ".codex",
            tmp_path / "keepygaga.toml",
            python=python,
            codex_binary=codex,
        )

    assert calls == [["mcp", "get", "keepygaga", "--json"]]


def test_mcp_registration_refuses_unpreservable_customization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    payload = {
        "enabled": True,
        "startup_timeout_sec": 30.0,
        "transport": {
            "type": "stdio",
            "command": "/old/python",
            "args": ["-m", "keepygaga.server"],
            "env": None,
            "env_vars": [],
            "cwd": None,
        },
    }
    monkeypatch.setattr(
        host_setup,
        "_run_codex",
        lambda _binary, _home, arguments: subprocess.CompletedProcess(
            arguments, 0, json.dumps(payload), ""
        ),
    )
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    with pytest.raises(HostSetupError, match="startup_timeout_sec"):
        host_setup.reconcile_codex_mcp(
            tmp_path / ".codex",
            tmp_path / "keepygaga.toml",
            python=python,
            codex_binary=codex,
        )


@pytest.mark.skipif(os.name == "nt", reason="executable bits are POSIX-specific")
def test_python_probe_rejects_non_executable_file(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o600)

    with pytest.raises(HostSetupError, match="not executable"):
        host_setup._probe_keepygaga_python(python)


@pytest.mark.skipif(os.name == "nt", reason="shell-script fixture is POSIX-specific")
def test_python_probe_rejects_successful_non_python_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)

    with pytest.raises(HostSetupError, match="probe failed"):
        host_setup._probe_keepygaga_python(wrapper)


@pytest.mark.skipif(os.name == "nt", reason="symlink fixture is Unix-specific")
def test_mcp_registration_preserves_virtualenv_python_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter = tmp_path / "python-real"
    interpreter.touch()
    venv_python = tmp_path / ".venv/bin/python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(interpreter)
    codex = tmp_path / "codex"
    codex.touch()
    codex.chmod(0o755)
    config = tmp_path / "keepygaga.toml"
    calls: list[list[str]] = []

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[1] == "get" and len(calls) == 1:
            return subprocess.CompletedProcess(
                arguments,
                1,
                "",
                "No MCP server named 'keepygaga' found.",
            )
        if arguments[1] == "add":
            return subprocess.CompletedProcess(arguments, 0, "Added", "")
        payload = {
            "enabled": True,
            "transport": {
                "type": "stdio",
                "command": str(venv_python),
                "args": ["-m", "keepygaga.server"],
                "env": {"KEEPYGAGA_CONFIG": str(config)},
                "env_vars": [],
                "cwd": None,
            },
        }
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    host_setup.reconcile_codex_mcp(
        tmp_path / ".codex", config, python=venv_python, codex_binary=codex
    )

    assert calls[1][-3:] == [str(venv_python), "-m", "keepygaga.server"]


def test_hooks_delegate_merge_and_preserve_unrelated_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "renamed-runtime"
    (runtime / "agent_hook_runtime").mkdir(parents=True)
    (runtime / "config/hooks").mkdir(parents=True)
    (runtime / "hooks").mkdir()
    hook_python = Path(sys.executable)
    (runtime / "agent_hook_runtime/hook_config.py").write_text(
        "def merge_hook_fragment(existing, fragment):\n"
        "    result = dict(existing)\n"
        "    hooks = dict(result.get('hooks', {}))\n"
        "    markers = tuple(fragment['owned_command_markers'])\n"
        "    def owned(item):\n"
        "        command = str(item)\n"
        "        return any(marker in command for marker in markers)\n"
        "    hooks['SessionStart'] = [\n"
        "        item for item in hooks.get('SessionStart', [])\n"
        "        if 'old/context_hook.py' not in str(item) and not owned(item)\n"
        "    ] + fragment['payload']['SessionStart']\n"
        "    result['hooks'] = hooks\n"
        "    return result\n",
        encoding="utf-8",
    )
    fragment = {
        "schema": "agent-hook-runtime-hook-fragment-v1",
        "host": "codex",
        "merge_target": "hooks",
        "owned_command_markers": ["context_hook.py"],
        "payload": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"{{PYTHON}}" "{{RUNTIME_ROOT}}/hooks/context_hook.py" codex',
                        }
                    ]
                }
            ]
        },
    }
    (runtime / "config/hooks/codex.json").write_text(
        json.dumps(fragment), encoding="utf-8"
    )
    for name in ("context_hook.py", "memory_route_hook.py", "closeout_hook.py"):
        content = (
            "print('{\"hookSpecificOutput\": {}}')\n"
            if name == "context_hook.py"
            else "# fixture\n"
        )
        (runtime / "hooks" / name).write_text(content, encoding="utf-8")

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "third-party"}]},
                        {
                            "hooks": [
                                {"type": "command", "command": "old/context_hook.py"}
                            ]
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    memory_root = tmp_path / "memory"
    memory_root.mkdir()

    result = host_setup.reconcile_codex_hooks(
        codex_home,
        memory_root,
        runtime,
        hook_python,
        hook_config_path=hook_config,
    )
    second = host_setup.reconcile_codex_hooks(
        codex_home,
        memory_root,
        runtime,
        hook_python,
        hook_config_path=hook_config,
    )

    assert result["status"] == "applied"
    assert second["status"] == "no_op"
    installed = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    serialized = json.dumps(installed)
    assert "third-party" in serialized
    assert "old/context_hook.py" not in serialized
    commands = [
        hook["command"]
        for registration in installed["hooks"]["SessionStart"]
        for hook in registration["hooks"]
    ]
    expected_entrypoint = (runtime / "hooks/context_hook.py").as_posix()
    normalized_commands = [command.replace("\\", "/") for command in commands]
    assert sum(expected_entrypoint in command for command in normalized_commands) == 1
    assert json.loads(hook_config.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "memory_root": str(memory_root),
    }


def test_hook_preflight_rejects_conflicting_memory_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_MEMORY_ROOT", str(tmp_path / "stale"))

    with pytest.raises(HostSetupError, match="conflicts"):
        host_setup.reconcile_codex_hooks(
            tmp_path / ".codex",
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=hook_config,
        )


def test_hook_preflight_rejects_symlink_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    target = tmp_path / "real-config.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "config-link.json"
    link.symlink_to(target)
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(link))

    with pytest.raises(HostSetupError, match="symlink"):
        host_setup.reconcile_codex_hooks(
            tmp_path / ".codex",
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=link,
        )

    assert target.read_text(encoding="utf-8") == "{}\n"


def test_hook_preflight_rejects_symlink_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    fragment = runtime / "config/hooks/codex.json"
    target = tmp_path / "fragment.json"
    target.write_text(fragment.read_text(encoding="utf-8"), encoding="utf-8")
    fragment.unlink()
    fragment.symlink_to(target)
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))

    with pytest.raises(HostSetupError, match="must be a regular file"):
        host_setup.reconcile_codex_hooks(
            tmp_path / ".codex",
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=hook_config,
        )


def test_hook_preflight_rejects_symlink_hooks_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    target = tmp_path / "hooks-target.json"
    target.write_text('{"hooks": {}}\n', encoding="utf-8")
    (codex_home / "hooks.json").symlink_to(target)

    with pytest.raises(HostSetupError, match="refusing symlink target"):
        host_setup._prepare_codex_hooks(
            codex_home,
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=hook_config,
        )

    assert not hook_config.exists()


def test_hook_preflight_rejects_nonobject_merger_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    (runtime / "agent_hook_runtime/hook_config.py").write_text(
        "def merge_hook_fragment(existing, fragment):\n    return []\n",
        encoding="utf-8",
    )
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))

    with pytest.raises(HostSetupError, match="must return a JSON object"):
        host_setup._prepare_codex_hooks(
            tmp_path / ".codex",
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=hook_config,
        )


@pytest.mark.skipif(os.name == "nt", reason="executable bits are POSIX-specific")
def test_hook_preflight_rejects_nonexecutable_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _hook_python = minimal_hook_runtime(tmp_path)
    hook_python = tmp_path / "hook-python"
    hook_python.touch(mode=0o600)
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))

    with pytest.raises(HostSetupError, match="not executable"):
        host_setup._prepare_codex_hooks(
            tmp_path / ".codex",
            tmp_path / "memory",
            runtime,
            hook_python,
            hook_config_path=hook_config,
        )

    assert not hook_config.exists()


def test_hook_apply_refuses_concurrent_hooks_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    hook_config = tmp_path / "ahr-config.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    hooks_path = codex_home / "hooks.json"
    hooks_path.write_text('{"hooks": {}}\n', encoding="utf-8")
    plan = host_setup._prepare_codex_hooks(
        codex_home,
        tmp_path / "memory",
        runtime,
        hook_python,
        hook_config_path=hook_config,
    )
    concurrent = '{"hooks": {"SessionStart": [{"command": "other"}]}}\n'
    hooks_path.write_text(concurrent, encoding="utf-8")

    with pytest.raises(HostSetupError, match="write conflict"):
        host_setup._apply_codex_hooks_plan(plan)

    assert hooks_path.read_text(encoding="utf-8") == concurrent
    assert not hook_config.exists()


def test_hook_apply_refuses_concurrent_runtime_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    hook_config = tmp_path / "ahr-config.json"
    hook_config.write_text(
        '{"schema_version": 1, "memory_root": "/old"}\n', encoding="utf-8"
    )
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    plan = host_setup._prepare_codex_hooks(
        codex_home,
        tmp_path / "memory",
        runtime,
        hook_python,
        hook_config_path=hook_config,
    )
    concurrent = '{"schema_version": 1, "memory_root": "/concurrent"}\n'
    hook_config.write_text(concurrent, encoding="utf-8")

    with pytest.raises(HostSetupError, match="write conflict"):
        host_setup._apply_codex_hooks_plan(plan)

    assert hook_config.read_text(encoding="utf-8") == concurrent
    assert not (codex_home / "hooks.json").exists()


def test_host_source_rejects_non_memory_doctor_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    config = KeepygagaConfig(MemoryFilesConfig(root=str(memory_root)))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "error",
            "checks": [
                {"id": "memory_tree", "status": "ok", "details": {}},
                {"id": "config", "status": "error", "details": {}},
            ],
        },
    )

    with pytest.raises(HostSetupError, match="config"):
        host_common.validate_host_source(tmp_path / "keepygaga.toml", config)


def test_hook_config_refuses_unrelated_json(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"unrelated": true}\n', encoding="utf-8")

    with pytest.raises(HostSetupError, match="not an Agent Hook Runtime config"):
        host_setup._reconcile_hook_runtime_config(config, tmp_path / "memory")

    assert json.loads(config.read_text(encoding="utf-8")) == {"unrelated": True}


def test_hook_command_path_rejects_shell_expansion(tmp_path: Path) -> None:
    with pytest.raises(HostSetupError, match="unsafe shell characters"):
        host_setup._validate_hook_command_path(
            tmp_path / "$(touch injected)", label="runtime"
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell escaping only")
def test_hook_command_path_rejects_backslash(tmp_path: Path) -> None:
    with pytest.raises(HostSetupError, match="unsafe shell characters"):
        host_setup._validate_hook_command_path(tmp_path / "bad\\path", label="runtime")



def test_setup_accepts_dynamic_page_limit_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    config_path = tmp_path / "keepygaga.toml"
    config = KeepygagaConfig(MemoryFilesConfig(root=str(memory_root)))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "warning",
            "checks": [
                {
                    "id": "memory_tree",
                    "status": "warning",
                    "details": {"dynamic_page_limit_exceeded": True},
                }
            ],
        },
    )
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_plan",
        lambda _plan: {"status": "no_op"},
    )

    result = host_setup.setup_codex_host(
        config_path, config, codex_home=tmp_path / ".codex"
    )

    assert result["status"] == "no_op"
    assert result["doctor"] == "warning"


def test_setup_rejects_permission_warning_even_with_soft_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    config = KeepygagaConfig(MemoryFilesConfig(root=str(memory_root)))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "warning",
            "checks": [
                {
                    "id": "memory_tree",
                    "status": "warning",
                    "details": {
                        "split_recommended": True,
                        "dynamic_page_limit_exceeded": True,
                        "permission_warnings": [
                            {
                                "path": str(memory_root / "profile.md"),
                                "mode": "0o644",
                                "expected": "0o600",
                            }
                        ],
                    },
                }
            ],
        },
    )

    with pytest.raises(HostSetupError, match="memory tree did not pass Doctor"):
        host_common.validate_host_source(tmp_path / "keepygaga.toml", config)


def test_setup_rejects_permission_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    config = KeepygagaConfig(MemoryFilesConfig(root=str(memory_root)))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "warning",
            "checks": [
                {
                    "id": "memory_tree",
                    "status": "warning",
                    "details": {
                        "permission_warnings": [
                            {
                                "path": str(memory_root / "profile.md"),
                                "mode": "0o644",
                                "expected": "0o600",
                            }
                        ]
                    },
                }
            ],
        },
    )

    with pytest.raises(HostSetupError, match="memory tree did not pass Doctor"):
        host_common.validate_host_source(tmp_path / "keepygaga.toml", config)


def test_setup_accepts_valid_soft_limit_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    config_path = tmp_path / "keepygaga.toml"
    config = KeepygagaConfig(MemoryFilesConfig(root=str(memory_root)))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "warning",
            "checks": [
                {
                    "id": "memory_tree",
                    "status": "warning",
                    "details": {"split_recommended": True},
                }
            ],
        },
    )
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_plan",
        lambda _plan: {"status": "no_op"},
    )

    result = host_setup.setup_codex_host(
        config_path, config, codex_home=tmp_path / ".codex"
    )

    assert result["status"] == "no_op"
    assert result["doctor"] == "warning"


def test_setup_rejects_incomplete_hook_selection_before_writes(tmp_path: Path) -> None:
    config = KeepygagaConfig(MemoryFilesConfig(root=str(tmp_path / "memory")))
    codex_home = tmp_path / ".codex"

    with pytest.raises(HostSetupError, match="supplied together"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            config,
            codex_home=codex_home,
            hook_runtime=tmp_path / "runtime",
        )

    assert not codex_home.exists()


def test_setup_preflights_hook_config_before_host_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    hook_config = tmp_path / "ahr-config.json"
    hook_config.write_text('{"unrelated": true}\n', encoding="utf-8")
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(hook_config))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    called: list[str] = []
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: called.append("rules") or {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_mcp",
        lambda *_args, **_kwargs: called.append("mcp") or {"status": "no_op"},
    )

    with pytest.raises(HostSetupError, match="not an Agent Hook Runtime config"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
            codex_home=tmp_path / ".codex",
            hook_runtime=runtime,
            hook_python=hook_python,
            hook_config_path=hook_config,
        )

    assert called == []


def test_setup_preflights_mcp_before_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    called: list[str] = []
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: called.append("rules") or {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HostSetupError("Codex MCP preflight failed")
        ),
    )

    with pytest.raises(HostSetupError, match="Codex MCP preflight failed"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
            codex_home=tmp_path / ".codex",
        )

    assert called == []


def test_setup_applies_mcp_then_rules_then_optional_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    events: list[str] = []
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_hooks",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_plan",
        lambda _plan: events.append("mcp") or {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: events.append("rules") or {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_hooks_plan",
        lambda _plan: events.append("hooks") or {"status": "no_op"},
    )

    result = host_setup.setup_codex_host(
        tmp_path / "keepygaga.toml",
        KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
        codex_home=tmp_path / ".codex",
        hook_runtime=tmp_path / "runtime",
        hook_python=tmp_path / "python",
    )

    assert result["status"] == "no_op"
    assert events == ["mcp", "rules", "hooks"]


def test_setup_does_not_apply_rules_when_mcp_apply_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    events: list[str] = []
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )

    def fail_mcp(_plan: object) -> dict[str, object]:
        events.append("mcp")
        raise HostSetupError("mcp apply failed")

    monkeypatch.setattr(host_setup, "_apply_codex_mcp_plan", fail_mcp)
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda _home: events.append("rules") or {"status": "applied"},
    )

    with pytest.raises(HostSetupError, match="mcp apply failed"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
            codex_home=tmp_path / ".codex",
        )

    assert events == ["mcp"]


@pytest.mark.skipif(os.name == "nt", reason="symlink fixture is Unix-specific")
def test_setup_rejects_symlink_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    target = tmp_path / "real-codex-home"
    target.mkdir()
    link = tmp_path / "codex-home-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )

    with pytest.raises(HostSetupError, match="must not be a symlink"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
            codex_home=link,
        )

    assert list(target.iterdir()) == []


def test_setup_reports_codex_home_file_as_host_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    codex_home = tmp_path / ".codex"
    codex_home.write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )

    with pytest.raises(HostSetupError, match="not a directory"):
        host_setup.setup_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
            codex_home=codex_home,
        )


def test_setup_treats_empty_codex_home_environment_as_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", "   ")
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    seen: list[Path] = []

    def rules(home: Path) -> dict[str, object]:
        seen.append(home)
        return {"status": "no_op"}

    monkeypatch.setattr(host_setup, "reconcile_codex_rules", rules)
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_plan",
        lambda _plan: {"status": "no_op"},
    )

    host_setup.setup_codex_host(
        tmp_path / "keepygaga.toml",
        KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
    )

    assert seen == [tmp_path / ".codex"]


def test_setup_expands_explicit_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(
        host_common,
        "run_doctor",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "checks": [{"id": "memory_tree", "status": "ok", "details": {}}],
        },
    )
    seen: list[Path] = []
    monkeypatch.setattr(
        host_setup,
        "reconcile_codex_rules",
        lambda home: seen.append(home) or {"status": "no_op"},
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_plan",
        lambda _plan: {"status": "no_op"},
    )

    host_setup.setup_codex_host(
        tmp_path / "keepygaga.toml",
        KeepygagaConfig(MemoryFilesConfig(root=str(memory_root))),
        codex_home=Path("~/custom-codex"),
    )

    assert seen == [tmp_path / "custom-codex"]


def test_uninstall_codex_rules_removes_block_and_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    agents = home / "AGENTS.md"
    agents.write_text("# Existing\n" + canonical(), encoding="utf-8")

    first = host_setup.remove_codex_rules(home)
    second = host_setup.remove_codex_rules(home)

    assert first["status"] == "applied"
    assert second["status"] == "no_op"
    assert agents.read_text(encoding="utf-8") == "# Existing\n"


def test_uninstall_codex_mcp_removes_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "config.toml").write_text("[mcp_servers.keepygaga]\n", encoding="utf-8")
    calls: list[list[str]] = []
    present = True

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        nonlocal present
        calls.append(arguments)
        if arguments == ["mcp", "get", "keepygaga", "--json"]:
            if present:
                payload = {
                    "enabled": True,
                    "transport": {
                        "type": "stdio",
                        "command": str(python),
                        "args": ["-m", "keepygaga.server"],
                        "env": {"KEEPYGAGA_CONFIG": "/tmp/keepygaga.toml"},
                    },
                }
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(payload), ""
                )
            return subprocess.CompletedProcess(
                arguments, 1, "", "No MCP server named 'keepygaga' found."
            )
        if arguments == ["mcp", "remove", "keepygaga"]:
            present = False
            return subprocess.CompletedProcess(arguments, 0, "Removed", "")
        raise AssertionError(arguments)

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    first = host_setup._apply_codex_mcp_removal(
        host_setup._prepare_codex_mcp_removal(home, codex_binary=codex)
    )
    second = host_setup._apply_codex_mcp_removal(
        host_setup._prepare_codex_mcp_removal(home, codex_binary=codex)
    )

    assert first["status"] == "applied"
    assert second["status"] == "no_op"
    assert ["mcp", "remove", "keepygaga"] in calls


def test_uninstall_codex_does_not_require_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "AGENTS.md").write_text("# Existing\n" + canonical(), encoding="utf-8")
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp_removal",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_removal",
        lambda _plan: {"status": "no_op", "key": "keepygaga"},
    )
    called = {"doctor": False}
    monkeypatch.setattr(
        host_setup,
        "validate_host_source",
        lambda *_args, **_kwargs: called.__setitem__("doctor", True) or (tmp_path, {}),
    )

    result = host_setup.uninstall_codex_host(
        tmp_path / "keepygaga.toml",
        KeepygagaConfig(MemoryFilesConfig(root=str(tmp_path / "memory"))),
        codex_home=home,
    )

    assert called["doctor"] is False
    assert result["status"] == "applied"
    rules = result["rules"]
    hooks = result["hooks"]
    assert isinstance(rules, dict)
    assert isinstance(hooks, dict)
    assert rules["status"] == "applied"
    assert (home / "AGENTS.md").read_text(encoding="utf-8") == "# Existing\n"
    assert hooks["status"] == "skipped"

def test_uninstall_codex_refuses_corrupt_rules_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "AGENTS.md").write_text("<!-- KEEPYGAGA:START -->\nmissing end\n", encoding="utf-8")
    hooks = home / "hooks.json"
    hooks.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_mcp_removal",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_mcp_removal",
        lambda _plan: (_ for _ in ()).throw(AssertionError("mcp should not apply")),
    )
    monkeypatch.setattr(
        host_setup,
        "_prepare_codex_hook_strip",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        host_setup,
        "_apply_codex_hook_strip",
        lambda _plan: (_ for _ in ()).throw(AssertionError("hooks should not apply")),
    )

    with pytest.raises(HostSetupError, match="unmatched Keepygaga start marker"):
        host_setup.uninstall_codex_host(
            tmp_path / "keepygaga.toml",
            KeepygagaConfig(MemoryFilesConfig(root=str(tmp_path / "memory"))),
            codex_home=home,
            hook_runtime=tmp_path / "runtime",
            hook_python=Path(sys.executable),
        )

    assert (home / "AGENTS.md").read_text(encoding="utf-8") == (
        "<!-- KEEPYGAGA:START -->\nmissing end\n"
    )
    assert hooks.read_text(encoding="utf-8") == "{}"


def test_uninstall_codex_mcp_verification_error_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    codex = tmp_path / "codex"
    python.touch()
    codex.touch()
    codex.chmod(0o755)
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "config.toml").write_text("[mcp_servers.keepygaga]\n", encoding="utf-8")
    calls = 0

    def run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if arguments == ["mcp", "get", "keepygaga", "--json"] and calls == 1:
            payload = {
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": str(python),
                    "args": ["-m", "keepygaga.server"],
                    "env": {"KEEPYGAGA_CONFIG": "/tmp/keepygaga.toml"},
                },
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")
        if arguments == ["mcp", "remove", "keepygaga"]:
            return subprocess.CompletedProcess(arguments, 0, "Removed", "")
        raise host_setup.HostSetupError("Codex CLI could not be executed")

    monkeypatch.setattr(host_setup, "_run_codex", run)
    monkeypatch.setattr(host_setup, "_probe_keepygaga_python", lambda _python: None)

    with pytest.raises(host_setup.HostSetupPartialError) as error:
        host_setup._apply_codex_mcp_removal(
            host_setup._prepare_codex_mcp_removal(home, codex_binary=codex)
        )

    payload = error.value.components["mcp"]
    assert isinstance(payload, dict)
    assert payload["status"] == "applied"
    assert payload["verified"] is False
    recovery = payload["recovery"]
    assert isinstance(recovery, dict)
    assert recovery["action"] == "restore_file"
