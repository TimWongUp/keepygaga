from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from keepygaga.config import MemoryFilesConfig
from keepygaga.hooks import (
    build_fragment,
    closeout,
    context,
    fragments,
    merge_hook_fragment,
    route,
)
from keepygaga.host_common import HostSetupError
from keepygaga.memory import initialize_memory_tree


def _commands(value: object) -> list[str]:
    if isinstance(value, dict):
        direct = value.get("command")
        found = [direct] if isinstance(direct, str) else []
        return found + [
            command for nested in value.values() for command in _commands(nested)
        ]
    if isinstance(value, list):
        return [command for nested in value for command in _commands(nested)]
    return []


def test_builtin_fragment_is_idempotent_and_preserves_unrelated(tmp_path: Path) -> None:
    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
    )
    existing = {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "other-hook"}]}]
        },
        "unrelated": True,
    }

    first = merge_hook_fragment(existing, fragment)
    second = merge_hook_fragment(first, fragment)

    assert second == first
    assert second["unrelated"] is True
    commands = _commands(second)
    assert "other-hook" in commands
    normalized = [command.replace('"', "") for command in commands]
    assert any("hook run context" in command for command in normalized)
    assert any("hook run route" in command for command in normalized)
    assert any("hook run closeout" in command for command in normalized)


def test_builtin_fragment_replaces_entries_after_launcher_and_config_move(
    tmp_path: Path,
) -> None:
    old_fragment = build_fragment(
        "codex",
        launcher=tmp_path / "old" / "keepygaga",
        config_path=tmp_path / "old" / "config.toml",
    )
    new_fragment = build_fragment(
        "codex",
        launcher=tmp_path / "new" / "keepygaga",
        config_path=tmp_path / "new" / "config.toml",
    )

    installed = merge_hook_fragment({}, old_fragment)
    migrated = merge_hook_fragment(installed, new_fragment)
    commands = _commands(migrated)

    assert all(str(tmp_path / "old") not in command for command in commands)
    assert sum(command.count("--owner=keepygaga-hook-v1") for command in commands) == 5
    assert any(str(tmp_path / "new" / "keepygaga") in command for command in commands)


def test_hook_merge_preserves_unrelated_generic_command(tmp_path: Path) -> None:
    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
    )
    existing = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/other hook run context --keep",
                        }
                    ]
                }
            ]
        }
    }

    merged = merge_hook_fragment(existing, fragment)

    assert "/usr/local/bin/other hook run context --keep" in json.dumps(merged)


def test_hook_merge_preserves_legacy_looking_third_party_command(
    tmp_path: Path,
) -> None:
    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
    )
    commands = [
        "/Users/u/.codex/hooks/context_hook.py --third-party",
        f"{tmp_path}/keepygaga-custom --config {tmp_path}/config.toml.bak hook run context --third-party",
    ]
    existing = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": command}]}
                for command in commands
            ]
        }
    }

    merged = merge_hook_fragment(existing, fragment)

    assert all(command in _commands(merged) for command in commands)


def test_hook_merge_preserves_owner_lookalike_commands(tmp_path: Path) -> None:
    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
    )
    commands = [
        "echo --owner=keepygaga-hook-v1",
        "/usr/local/bin/other --owner=keepygaga-hook-v1x",
    ]
    existing = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": command}]}
                for command in commands
            ]
        }
    }

    rendered = json.dumps(merge_hook_fragment(existing, fragment))

    assert all(command in rendered for command in commands)


def test_hook_merge_removes_exact_legacy_external_runtime_command(
    tmp_path: Path,
) -> None:
    fragment = build_fragment(
        "grok",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
        enabled=False,
    )
    owned = (
        '"/venv/bin/python" '
        f'"{Path.home()}/Code/agent-hook-runtime/hooks/closeout_hook.py" grok Stop'
    )
    unrelated = (
        '"/venv/bin/python" '
        '"/Users/tim/Code/agent-hook-runtime-custom/hooks/closeout_hook.py" grok Stop'
    )
    existing = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": owned}]},
                {"hooks": [{"type": "command", "command": unrelated}]},
            ]
        }
    }

    merged = merge_hook_fragment(existing, fragment)
    rendered = json.dumps(merged)
    remaining = json.dumps(merged["hooks"]["Stop"])  # type: ignore[index]

    assert owned not in rendered
    assert "agent-hook-runtime-custom" in remaining


def test_hook_merge_preserves_external_runtime_path_lookalike(tmp_path: Path) -> None:
    fragment = build_fragment(
        "grok",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config.toml",
        enabled=False,
    )
    command = (
        '"/venv/bin/python" '
        '"/usr/local/evil/agent-hook-runtime/hooks/closeout_hook.py" grok Stop'
    )
    existing = {
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]}
    }

    merged = merge_hook_fragment(existing, fragment)
    assert merged["hooks"]["Stop"][0]["hooks"][0]["command"] == command


def test_context_bootstrap_contains_home_pages_and_catalog(tmp_path: Path) -> None:
    memory_root = tmp_path / "agents-memory"
    initialize_memory_tree(memory_root, MemoryFilesConfig(root=str(memory_root)))
    config = tmp_path / "config.toml"
    config.write_text(
        f"[memory]\nroot = {json.dumps(str(memory_root))}\n", encoding="utf-8"
    )

    rendered = context.load_bootstrap(config)

    assert "<profile version=" in rendered
    assert "<preferences version=" in rendered
    assert "<memory_listing>" in rendered


def test_route_state_stores_no_raw_prompt_and_closeout_deduplicates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "s1", "prompt": "请修改这个项目的代码"}

    route.record("codex", payload)
    state = route.state_path("codex", payload).read_text(encoding="utf-8")

    assert payload["prompt"] not in state
    assert closeout.run("codex", "PostToolUse", payload)
    assert closeout.run("codex", "PostToolUse", payload) == {}

    route.record("codex", payload)
    assert closeout.run("codex", "PostToolUse", payload)


def test_compact_route_without_prompt_preserves_closeout_signal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    prompt = {"session_id": "s1", "prompt": "请修改这个项目的代码"}
    compact = {"session_id": "s1"}

    route.record("codex", prompt)
    route.run("codex", "SessionStart", compact, compact=True)

    assert closeout.run("codex", "PostToolUse", compact)


def test_route_without_session_identity_does_not_share_cwd_state(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))

    result = route.run(
        "codex", "UserPromptSubmit", {"cwd": "/shared", "prompt": "修改代码"}
    )

    assert result
    assert list(tmp_path.glob("*.json")) == []


def test_route_rejects_symlinked_state_root_ancestor(
    tmp_path: Path, monkeypatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(linked / "nested"))

    with pytest.raises(OSError, match="linked Hook state directory"):
        route.record("codex", {"session_id": "s1", "prompt": "修改代码"})

    assert not (outside / "nested").exists()


def test_grok_closeout_honors_reentry_guard() -> None:
    assert closeout.run("grok", "Stop", {"reason": "end_turn"})
    assert (
        closeout.run("grok", "Stop", {"reason": "end_turn", "stop_hook_active": True})
        == {}
    )


def test_antigravity_uninstall_fragment_targets_installed_group(tmp_path: Path) -> None:
    install = build_fragment(
        "antigravity", launcher=tmp_path / "keepygaga", config_path=tmp_path / "config"
    )
    uninstall = build_fragment(
        "antigravity",
        launcher=tmp_path / "keepygaga",
        config_path=tmp_path / "config",
        enabled=False,
    )

    installed = merge_hook_fragment({}, install)
    removed = merge_hook_fragment(installed, uninstall)

    assert removed["shared-context-bootstrap"] == {}


def test_windows_owner_marker_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fragments.os, "name", "nt")
    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "keepygaga.exe",
        config_path=tmp_path / "config.toml",
    )

    first = merge_hook_fragment({}, fragment)
    second = merge_hook_fragment(first, fragment)

    assert second == first


def test_windows_hook_path_rejects_environment_expansion(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fragments.os, "name", "nt")

    try:
        build_fragment(
            "codex",
            launcher=tmp_path / "keepygaga.exe",
            config_path=Path("C:/Users/Tim/cfg%TEMP%.toml"),
        )
    except HostSetupError as exc:
        assert "unsafe shell characters" in str(exc)
    else:
        raise AssertionError("expected unsafe Windows path rejection")


@pytest.mark.skipif(os.name != "nt", reason="Windows command shell regression")
def test_windows_codex_command_executes_through_command_shell(tmp_path: Path) -> None:
    launcher_value = shutil.which("keepygaga")
    assert launcher_value is not None
    launcher = Path(launcher_value).resolve()
    assert " " not in str(launcher)

    memory_root = tmp_path / "中文 memory root" / "agents-memory"
    initialize_memory_tree(memory_root, MemoryFilesConfig(root=str(memory_root)))
    config_path = tmp_path / "config with spaces" / "keepygaga.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        f"[memory]\nroot = {json.dumps(str(memory_root))}\n", encoding="utf-8"
    )
    fragment = build_fragment(
        "codex", launcher=launcher, config_path=config_path.resolve()
    )
    command = fragment["payload"]["SessionStart"][0]["hooks"][0]["command"]

    completed = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        encoding="utf-8",
        input=json.dumps({"session_id": "windows-command-smoke"}),
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "<keepygaga-bootstrap>" in payload["hookSpecificOutput"][
        "additionalContext"
    ]
