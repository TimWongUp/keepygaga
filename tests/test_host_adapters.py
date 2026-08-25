from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

from keepygaga import host_adapters
from keepygaga.config import KeepygagaConfig, MemoryFilesConfig
from keepygaga.host_adapters import (
    setup_antigravity_host,
    setup_claude_code_host,
    setup_grok_host,
    setup_hermes_host,
    setup_workbuddy_host,
)
from keepygaga.host_common import HostSetupError, HostSetupPartialError
from keepygaga.memory import initialize_memory_tree

SetupFunction = Callable[..., dict[str, object]]


def setup_source(tmp_path: Path) -> tuple[Path, KeepygagaConfig]:
    memory_root = tmp_path / "memory"
    memory = MemoryFilesConfig(root=str(memory_root))
    initialize_memory_tree(memory_root, memory)
    config_path = tmp_path / "keepygaga.toml"
    config_path.write_text(
        f'[memory]\nroot = "{memory_root.as_posix()}"\n', encoding="utf-8"
    )
    return config_path, KeepygagaConfig(memory=memory)


@pytest.mark.parametrize(
    ("setup", "home_name", "mcp_relative", "rules_relative"),
    [
        (setup_claude_code_host, ".claude", "../.claude.json", "CLAUDE.md"),
        (setup_workbuddy_host, ".workbuddy", "mcp.json", "CODEBUDDY.md"),
        (
            setup_antigravity_host,
            ".gemini",
            "config/mcp_config.json",
            "AGENTS.md",
        ),
    ],
)
def test_json_host_setup_is_idempotent_and_preserves_unrelated_config(
    tmp_path: Path,
    setup: SetupFunction,
    home_name: str,
    mcp_relative: str,
    rules_relative: str,
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / home_name
    home.mkdir()
    mcp_path = (home / mcp_relative).resolve()
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(
        json.dumps(
            {
                "unrelated": {"keep": True},
                "mcpServers": {
                    "other": {"command": "other"},
                    "keepygaga": {
                        "type": "http",
                        "serverUrl": "https://old.invalid/sse",
                        "url": "https://old.invalid/mcp",
                        "env": {"CUSTOM": "preserved"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    rules_path = home / rules_relative
    rules_path.write_text("# Existing rules\n", encoding="utf-8")

    first = setup(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
    )

    assert first["status"] == "applied"
    loaded = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert loaded["unrelated"] == {"keep": True}
    assert loaded["mcpServers"]["other"] == {"command": "other"}
    registration = loaded["mcpServers"]["keepygaga"]
    assert registration["command"] == str(Path(sys.executable))
    assert registration["args"] == ["-m", "keepygaga.server"]
    assert "url" not in registration
    assert "serverUrl" not in registration
    if setup in {setup_claude_code_host, setup_workbuddy_host}:
        assert registration["type"] == "stdio"
    else:
        assert "type" not in registration
    assert registration["env"] == {
        "CUSTOM": "preserved",
        "KEEPYGAGA_CONFIG": str(config_path),
    }
    rules = rules_path.read_text(encoding="utf-8")
    assert rules.startswith("# Existing rules\n")
    assert rules.count("<!-- KEEPYGAGA:START -->") == 1

    second = setup(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
    )

    assert second["status"] == "no_op"
    assert second["mcp"]["status"] == "no_op"  # type: ignore[index]
    assert second["rules"]["status"] == "no_op"  # type: ignore[index]


def test_json_host_rejects_malformed_config_before_writing_rules(
    tmp_path: Path,
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".workbuddy"
    home.mkdir()
    mcp_path = home / "mcp.json"
    original = b"{malformed"
    mcp_path.write_bytes(original)

    with pytest.raises(HostSetupError, match="invalid JSON"):
        setup_workbuddy_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert mcp_path.read_bytes() == original
    assert not (home / "CODEBUDDY.md").exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink semantics differ on Windows"
)
def test_json_host_rejects_symlink_config_before_writing_rules(
    tmp_path: Path,
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".workbuddy"
    home.mkdir()
    actual = tmp_path / "actual-mcp.json"
    actual.write_text("{}\n", encoding="utf-8")
    (home / "mcp.json").symlink_to(actual)

    with pytest.raises(HostSetupError, match="symlink"):
        setup_workbuddy_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert actual.read_text(encoding="utf-8") == "{}\n"
    assert not (home / "CODEBUDDY.md").exists()


def test_json_host_rejects_duplicate_rules_block_before_writing_mcp(
    tmp_path: Path,
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".workbuddy"
    home.mkdir()
    mcp_path = home / "mcp.json"
    mcp_path.write_text("{}\n", encoding="utf-8")
    managed = (
        "<!-- KEEPYGAGA:START -->\n"
        "<!-- KEEPYGAGA:END -->\n"
        "<!-- KEEPYGAGA:START -->\n"
        "<!-- KEEPYGAGA:END -->\n"
    )
    (home / "CODEBUDDY.md").write_text(managed, encoding="utf-8")

    with pytest.raises(HostSetupError, match="duplicate"):
        setup_workbuddy_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert mcp_path.read_text(encoding="utf-8") == "{}\n"


def test_json_host_reports_partial_commit_after_mcp_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".workbuddy"
    home.mkdir()
    original_apply = host_adapters._apply_file

    def fail_rules(plan: host_adapters.FilePlan) -> dict[str, object]:
        if plan.path.name == "CODEBUDDY.md":
            raise HostSetupError("simulated rules failure")
        return original_apply(plan)

    monkeypatch.setattr(host_adapters, "_apply_file", fail_rules)

    with pytest.raises(HostSetupPartialError) as caught:
        setup_workbuddy_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert caught.value.components["mcp"]["status"] == "applied"  # type: ignore[index]
    assert "keepygaga" in (home / "mcp.json").read_text(encoding="utf-8")
    assert not (home / "CODEBUDDY.md").exists()


def minimal_hook_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    (runtime / "agent_hook_runtime").mkdir(parents=True)
    (runtime / "config/hooks").mkdir(parents=True)
    (runtime / "hooks").mkdir()
    (runtime / "agent_hook_runtime/hook_config.py").write_text(
        """
from copy import deepcopy

def owned(value, markers):
    if isinstance(value, dict):
        command = value.get('command')
        if isinstance(command, str) and any(marker in command for marker in markers):
            return None
        cleaned = {key: result for key, nested in value.items() if (result := owned(nested, markers)) is not None}
        if 'hooks' in value and not cleaned.get('hooks'):
            return None
        return cleaned
    if isinstance(value, list):
        return [result for nested in value if (result := owned(nested, markers)) is not None]
    return value

def merge_hook_fragment(existing, fragment):
    merged = deepcopy(existing)
    target = fragment['merge_target']
    current = owned(merged.get(target, {}), fragment['owned_command_markers'])
    for event, entries in fragment['payload'].items():
        current.setdefault(event, []).extend(deepcopy(entries))
    merged[target] = current
    return merged
""".lstrip(),
        encoding="utf-8",
    )
    (runtime / "config/hooks/workbuddy.json").write_text(
        json.dumps(
            {
                "host": "workbuddy",
                "merge_target": "hooks",
                "owned_command_markers": ["context_hook.py"],
                "payload": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "command": '"{{PYTHON}}" "{{RUNTIME_ROOT}}/hooks/context_hook.py" workbuddy',
                                    "timeout": 10,
                                }
                            ]
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (runtime / "config/hooks/hermes.json").write_text(
        json.dumps(
            {
                "host": "hermes",
                "merge_target": "hooks",
                "owned_command_markers": ["context_hook.py"],
                "payload": {
                    "session_start": [
                        {
                            "command": '"{{PYTHON}}" "{{RUNTIME_ROOT}}/hooks/context_hook.py" hermes'
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    for name in ("context_hook.py", "memory_route_hook.py", "closeout_hook.py"):
        (runtime / "hooks" / name).write_text("# fixture\n", encoding="utf-8")
    return runtime, Path(sys.executable)


def test_workbuddy_hook_merge_preserves_unrelated_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".workbuddy"
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps(
            {
                "other": True,
                "hooks": {
                    "PostToolUse": [{"hooks": [{"command": "prettier", "timeout": 5}]}]
                },
            }
        ),
        encoding="utf-8",
    )
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    runtime_config = tmp_path / "ahr.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(runtime_config))

    first = setup_workbuddy_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        hook_runtime=runtime,
        hook_python=hook_python,
        hook_config_path=runtime_config,
    )

    assert first["hooks"]["status"] == "applied"  # type: ignore[index]
    loaded = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert loaded["other"] is True
    assert loaded["hooks"]["PostToolUse"] == [
        {"hooks": [{"command": "prettier", "timeout": 5}]}
    ]
    assert (
        "context_hook.py" in loaded["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    )

    second = setup_workbuddy_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        hook_runtime=runtime,
        hook_python=hook_python,
        hook_config_path=runtime_config,
    )
    assert second["status"] == "no_op"


def test_grok_setup_uses_user_cli_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".grok"
    home.mkdir()
    (home / "config.toml").write_text("[unrelated]\nkeep = true\n", encoding="utf-8")
    (home / "AGENTS.md").write_text("# Existing Grok rules\n", encoding="utf-8")
    fake_binary = Path(sys.executable)
    registrations: list[dict[str, Any]] = []
    add_calls = 0

    def fake_run(
        binary: Path, selected_home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        nonlocal add_calls
        del binary, selected_home
        if arguments == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(
                arguments, 0, json.dumps(registrations), ""
            )
        assert arguments == [
            "mcp",
            "add",
            "--scope",
            "user",
            "--env",
            f"KEEPYGAGA_CONFIG={config_path}",
            "keepygaga",
            "--",
            str(Path(sys.executable)),
            "-m",
            "keepygaga.server",
        ]
        add_calls += 1
        registrations[:] = [
            {
                "name": "keepygaga",
                "scope": "user",
                "enabled": True,
                "command": str(Path(sys.executable)),
                "args": ["-m", "keepygaga.server"],
                "env": {"KEEPYGAGA_CONFIG": str(config_path)},
            }
        ]
        (home / "config.toml").write_text(
            "[unrelated]\nkeep = true\n\n[mcp_servers.keepygaga]\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(host_adapters, "_run_grok", fake_run)

    first = setup_grok_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        grok_binary=fake_binary,
    )
    second = setup_grok_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        grok_binary=fake_binary,
    )

    assert first["status"] == "applied"
    assert first["mcp"]["status"] == "applied"  # type: ignore[index]
    assert second["status"] == "no_op"
    assert second["mcp"]["status"] == "no_op"  # type: ignore[index]
    assert add_calls == 1
    assert registrations == [
        {
            "name": "keepygaga",
            "scope": "user",
            "enabled": True,
            "command": str(Path(sys.executable)),
            "args": ["-m", "keepygaga.server"],
            "env": {"KEEPYGAGA_CONFIG": str(config_path)},
        }
    ]
    assert "[unrelated]\nkeep = true" in (home / "config.toml").read_text(
        encoding="utf-8"
    )
    assert (home / "AGENTS.md").read_text(encoding="utf-8").count(
        "<!-- KEEPYGAGA:START -->"
    ) == 1
    assert "Agents.md" not in {entry.name for entry in home.iterdir()}


def test_grok_reports_partial_commit_when_cli_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".grok"
    home.mkdir()

    def fake_run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        if arguments == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(arguments, 0, "[]", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(host_adapters, "_run_grok", fake_run)

    with pytest.raises(HostSetupPartialError) as caught:
        setup_grok_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
            grok_binary=Path(sys.executable),
        )

    mcp = caught.value.components["mcp"]
    assert mcp["status"] == "applied"  # type: ignore[index]
    assert mcp["verified"] is False  # type: ignore[index]
    assert mcp["recovery"]["action"] == "remove_new_registration"  # type: ignore[index]


def test_grok_partial_commit_preserves_backup_for_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".grok"
    home.mkdir()
    grok_config = home / "config.toml"
    original = b"[unrelated]\nkeep = true\n"
    grok_config.write_bytes(original)

    def fake_run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        if arguments == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(arguments, 0, "[]", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(host_adapters, "_run_grok", fake_run)

    with pytest.raises(HostSetupPartialError) as caught:
        setup_grok_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
            grok_binary=Path(sys.executable),
        )

    recovery = caught.value.components["mcp"]["recovery"]  # type: ignore[index]
    backup = Path(recovery["source"])
    assert recovery == {
        "action": "restore_file",
        "source": str(backup),
        "destination": str(grok_config),
    }
    assert backup.read_bytes() == original


def test_grok_rejects_duplicate_user_registrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".grok"
    home.mkdir()
    duplicate = [
        {"name": "keepygaga", "scope": "user"},
        {"name": "keepygaga", "scope": "user"},
    ]
    calls: list[list[str]] = []

    def fake_run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(duplicate), "")

    monkeypatch.setattr(host_adapters, "_run_grok", fake_run)

    with pytest.raises(HostSetupError, match="duplicate"):
        setup_grok_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
            grok_binary=Path(sys.executable),
        )

    assert not (home / "Agents.md").exists()
    assert calls == [["mcp", "list", "--json"]]


def test_grok_rejects_managed_blocks_in_both_rules_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".grok"
    home.mkdir()
    managed = host_adapters.load_canonical_contract()
    upper = tmp_path / "upper/AGENTS.md"
    title = tmp_path / "title/Agents.md"
    upper.parent.mkdir()
    title.parent.mkdir()
    upper.write_text(managed, encoding="utf-8")
    title.write_text(managed, encoding="utf-8")
    original_iterdir = Path.iterdir

    def fake_iterdir(path: Path):
        return iter((upper, title)) if path == home else original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(host_adapters.os.path, "samefile", lambda *_args: False)
    registration = [
        {
            "name": "keepygaga",
            "scope": "user",
            "enabled": True,
            "command": str(Path(sys.executable)),
            "args": ["-m", "keepygaga.server"],
            "env": {"KEEPYGAGA_CONFIG": str(config_path)},
        }
    ]
    calls: list[list[str]] = []

    def fake_run(
        _binary: Path, _home: Path, arguments: list[str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(registration), "")

    monkeypatch.setattr(host_adapters, "_run_grok", fake_run)

    with pytest.raises(HostSetupError, match="duplicate"):
        setup_grok_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
            grok_binary=Path(sys.executable),
        )

    assert calls == [["mcp", "list", "--json"]]


def test_hermes_setup_merges_yaml_and_manages_global_soul(tmp_path: Path) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "# keep this comment\n"
        "model: existing\n"
        "mcp_servers:\n"
        "  other:\n"
        "    command: other\n"
        "  keepygaga:\n"
        "    type: http\n"
        "    url: https://old.invalid/mcp\n",
        encoding="utf-8",
    )
    (home / "SOUL.md").write_text("# Existing personality\n", encoding="utf-8")

    first = setup_hermes_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
    )
    loaded = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    second = setup_hermes_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
    )

    assert first["status"] == "applied"
    assert loaded["model"] == "existing"
    assert loaded["mcp_servers"]["other"] == {"command": "other"}
    assert loaded["mcp_servers"]["keepygaga"]["args"] == [
        "-m",
        "keepygaga.server",
    ]
    assert "type" not in loaded["mcp_servers"]["keepygaga"]
    assert "url" not in loaded["mcp_servers"]["keepygaga"]
    assert (
        (home / "config.yaml")
        .read_text(encoding="utf-8")
        .startswith("# keep this comment\n")
    )
    assert (
        (home / "SOUL.md")
        .read_text(encoding="utf-8")
        .startswith("# Existing personality\n")
    )
    assert second["status"] == "no_op"


def test_hermes_hook_merge_is_idempotent_and_preserves_unrelated_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "hooks:\n  other_event:\n    - command: other\n", encoding="utf-8"
    )
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    runtime_config = tmp_path / "ahr.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(runtime_config))

    first = setup_hermes_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        hook_runtime=runtime,
        hook_python=hook_python,
        hook_config_path=runtime_config,
    )
    second = setup_hermes_host(
        config_path,
        config,
        host_home=home,
        python=Path(sys.executable),
        hook_runtime=runtime,
        hook_python=hook_python,
        hook_config_path=runtime_config,
    )

    loaded = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert first["hooks"]["status"] == "applied"  # type: ignore[index]
    assert first["hooks"]["approval_required"] is True  # type: ignore[index]
    assert first["hooks"]["runtime_config"]["status"] == "applied"  # type: ignore[index]
    assert json.loads(runtime_config.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "memory_root": str(Path(config.memory.root).resolve()),
    }
    assert loaded["hooks"]["other_event"] == [{"command": "other"}]
    assert "context_hook.py" in loaded["hooks"]["session_start"][0]["command"]
    assert second["status"] == "no_op"


def test_hermes_reports_partial_commit_after_config_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    original_apply = host_adapters._apply_file

    def fail_rules(plan: host_adapters.FilePlan) -> dict[str, object]:
        if plan.path.name == "SOUL.md":
            raise HostSetupError("simulated rules failure")
        return original_apply(plan)

    monkeypatch.setattr(host_adapters, "_apply_file", fail_rules)

    with pytest.raises(HostSetupPartialError) as caught:
        setup_hermes_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert caught.value.components["mcp"]["status"] == "applied"  # type: ignore[index]
    assert "keepygaga" in (home / "config.yaml").read_text(encoding="utf-8")
    assert not (home / "SOUL.md").exists()


def test_hermes_reports_partial_commit_when_hook_runtime_config_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    runtime, hook_python = minimal_hook_runtime(tmp_path)
    runtime_config = tmp_path / "ahr.json"
    monkeypatch.setenv("AGENT_HOOK_RUNTIME_CONFIG", str(runtime_config))
    original_apply = host_adapters._apply_file

    def fail_runtime(plan: host_adapters.FilePlan) -> dict[str, object]:
        if plan.path == runtime_config:
            raise HostSetupError("simulated runtime config failure")
        return original_apply(plan)

    monkeypatch.setattr(host_adapters, "_apply_file", fail_runtime)

    with pytest.raises(HostSetupPartialError) as caught:
        setup_hermes_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
            hook_runtime=runtime,
            hook_python=hook_python,
            hook_config_path=runtime_config,
        )

    assert caught.value.components["mcp"]["status"] == "applied"  # type: ignore[index]
    assert caught.value.components["hooks"]["status"] == "applied"  # type: ignore[index]
    assert caught.value.components["rules"]["status"] == "applied"  # type: ignore[index]
    assert not runtime_config.exists()


def test_yaml_round_trip_runtime_is_thread_safe(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    original = '# leading comment\nquoted: "keep" # inline\nitems:\n  - one\n'
    path.write_text(original, encoding="utf-8")

    def round_trip() -> bytes:
        _original, loaded = host_adapters._load_yaml_object(path)
        return host_adapters._yaml_bytes(loaded)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: round_trip(), range(200)))

    assert all(result == results[0] for result in results)
    rendered = results[0].decode()
    assert rendered.startswith("# leading comment\n")
    assert 'quoted: "keep" # inline' in rendered
    assert rendered.index("quoted:") < rendered.index("items:")
    assert host_adapters._yaml_runtime() is not host_adapters._yaml_runtime()


def test_hermes_rejects_malformed_yaml_before_writing_rules(tmp_path: Path) -> None:
    config_path, config = setup_source(tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    config_file = home / "config.yaml"
    original = "mcp_servers: [unterminated\n"
    config_file.write_text(original, encoding="utf-8")

    with pytest.raises(HostSetupError, match="invalid YAML"):
        setup_hermes_host(
            config_path,
            config,
            host_home=home,
            python=Path(sys.executable),
        )

    assert config_file.read_text(encoding="utf-8") == original
    assert not (home / "SOUL.md").exists()
