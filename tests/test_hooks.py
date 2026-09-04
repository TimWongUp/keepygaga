from __future__ import annotations

import base64
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
from keepygaga.memory import CreateOperation, Fact, MemoryStore, initialize_memory_tree


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


def _decoded_config_path(command: str) -> str:
    token = command.split("--config-base64 ", 1)[1].split(" ", 1)[0]
    return base64.urlsafe_b64decode(token).decode("utf-8")


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


def test_context_bootstrap_contains_home_pages_and_scope_descriptions(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "agents-memory"
    memory_config = MemoryFilesConfig(root=str(memory_root))
    initialize_memory_tree(memory_root, memory_config)
    store = MemoryStore(memory_root, memory_config)
    assert (
        store.create(
            [
                CreateOperation(
                    path="people/not-in-bootstrap.md",
                    description="Must stay out of bootstrap.",
                    aliases=[],
                    facts=[Fact(basis="stated", content="Known person.")],
                ),
                CreateOperation(
                    path="areas/projects.md",
                    description="Must stay an on-demand project index.",
                    aliases=["project index"],
                    facts=[Fact(basis="observed", content="Project locator.")],
                ),
            ]
        )["status"]
        == "applied"
    )
    profile = memory_root / "profile.md"
    profile.write_text(
        profile.read_text(encoding="utf-8").rstrip()
        + "\n\n- [stated] Dated home fact. [2026-09-02]\n",
        encoding="utf-8",
    )
    preferences = memory_root / "preferences.md"
    preferences.write_text(
        preferences.read_text(encoding="utf-8").rstrip()
        + "\n\n- [observed] Legacy home fact.\n",
        encoding="utf-8",
    )
    (memory_root / "areas" / "broken.md").write_text(
        "malformed dynamic page\n", encoding="utf-8"
    )
    config = tmp_path / "config.toml"
    config.write_text(
        f"[memory]\nroot = {json.dumps(str(memory_root))}\n", encoding="utf-8"
    )
    snapshots = {
        item["path"]: item["version"]
        for item in store.read(["profile.md", "preferences.md"])["files"]  # type: ignore[index]
    }

    rendered = context.load_bootstrap(config)

    assert f'<profile version="{snapshots["profile.md"]}">' in rendered
    assert f'<preferences version="{snapshots["preferences.md"]}">' in rendered
    assert "<memory_scopes>" in rendered
    assert "`topics`" in rendered
    assert "`areas`" in rendered
    assert "`people`" in rendered
    assert context.SCOPE_ROUTING in rendered
    assert "description 作为一级语义路由条件" in rendered
    assert "path、description 和 aliases" in rendered
    assert context.SCOPE_DESCRIPTIONS["areas"] == "持续活动、长期环境与项目索引。"
    assert all(
        "list(" not in description
        for description in context.SCOPE_DESCRIPTIONS.values()
    )
    assert "- [stated] Dated home fact. [2026-09-02]" in rendered
    assert "- [observed] Legacy home fact." in rendered
    assert "people/not-in-bootstrap.md" not in rendered
    assert "Must stay out of bootstrap." not in rendered
    assert "Known person." not in rendered
    assert "areas/projects.md" not in rendered
    assert "Must stay an on-demand project index." not in rendered
    assert "Project locator." not in rendered
    assert "malformed dynamic page" not in rendered
    for description in context.SCOPE_DESCRIPTIONS.values():
        assert rendered.count(description) == 1
    assert "<memory_listing>" not in rendered


def test_route_state_stores_no_raw_prompt_and_closeout_deduplicates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "s1", "prompt": "请修改这个项目的代码"}

    route.record("codex", payload)
    state = route.state_path("codex", payload).read_text(encoding="utf-8")

    assert payload["prompt"] not in state
    assert "prompt_hash" not in state
    assert closeout.run("codex", "PostToolUse", payload)
    assert closeout.run("codex", "PostToolUse", payload) == {}

    route.record("codex", payload)
    assert closeout.run("codex", "PostToolUse", payload)


def test_memory_hook_reminders_keep_noop_decisions_silent() -> None:
    for reminder in (route.REMINDER, route.COMPACT_REMINDER, closeout.REMINDER):
        assert "静默" in reminder
        assert "原任务" in reminder


def test_hermes_fragment_omits_unsupported_closeout() -> None:
    fragment = build_fragment(
        "hermes", launcher=Path("/keepygaga"), config_path=Path("/config.toml")
    )

    assert set(fragment["payload"]) == {"pre_llm_call"}
    assert all("closeout" not in command for command in _commands(fragment["payload"]))


def test_hermes_fragment_removes_obsolete_closeout_projection() -> None:
    fragment = build_fragment(
        "hermes", launcher=Path("/keepygaga"), config_path=Path("/config.toml")
    )
    existing = {
        "hooks": {
            "pre_verify": [
                {
                    "command": (
                        "/keepygaga --config /config.toml hook run closeout "
                        "--owner=keepygaga-hook-v1 --host hermes --event pre_verify"
                    ),
                    "timeout": 2,
                }
            ],
            "other_event": [{"command": "other"}],
        }
    }

    merged = merge_hook_fragment(existing, fragment)

    assert "pre_verify" not in merged["hooks"]
    assert merged["hooks"]["other_event"] == [{"command": "other"}]


def test_route_scrubs_legacy_prompt_hash_when_state_is_rewritten(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "legacy-s1"}
    state_path = route.state_path("codex", payload)
    legacy = {
        "version": 1,
        "updated_at": 9_999_999_999,
        "prompt_hash": "legacy-hash",
        "project_signal": True,
        "memory_signal": False,
        "reminded": False,
    }
    state_path.write_text(json.dumps(legacy), encoding="utf-8")

    route.record("codex", payload)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "prompt_hash" not in state
    state_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert route.consume_closeout("codex", payload)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "prompt_hash" not in state


def test_route_accepts_windows_surrogate_prompt_without_hashing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "s1", "prompt": "修复 Windows \ud800"}

    result = route.run("codex", "UserPromptSubmit", payload)

    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert hook_output["hookEventName"] == "UserPromptSubmit"
    state = json.loads(route.state_path("codex", payload).read_text(encoding="utf-8"))
    assert "prompt_hash" not in state
    assert state["project_signal"] is True


def test_route_accepts_windows_surrogate_session_identity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KEEPYGAGA_HOOK_STATE_ROOT", str(tmp_path))
    payload = {"session_id": "windows-\ud800", "prompt": "修改代码"}

    result = route.run("codex", "UserPromptSubmit", payload)

    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert hook_output["hookEventName"] == "UserPromptSubmit"
    assert route.state_path("codex", payload).is_file()


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


def test_grok_closeout_is_not_projected() -> None:
    fragment = build_fragment(
        "grok", launcher=Path("/keepygaga"), config_path=Path("/config.toml")
    )

    assert fragment["payload"] == {}
    assert closeout.run("grok", "Stop", {"reason": "end_turn"}) == {}


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
    command = fragment["payload"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith(str(tmp_path / "keepygaga.exe"))
    assert '"' not in command
    assert "--config-base64" in command
    assert _decoded_config_path(command) == str(tmp_path / "config.toml")
    hook = fragment["payload"]["SessionStart"][0]["hooks"][0]
    assert "env" not in hook


def test_windows_launcher_with_spaces_remains_quoted(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(fragments.os, "name", "nt")

    fragment = build_fragment(
        "codex",
        launcher=tmp_path / "Keepygaga Tool" / "keepygaga.exe",
        config_path=tmp_path / "config.toml",
    )

    command = fragment["payload"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith(f'"{tmp_path / "Keepygaga Tool" / "keepygaga.exe"}"')
    assert command.count('"') == 2
    assert "--config-base64" in command
    assert _decoded_config_path(command) == str(tmp_path / "config.toml")
    hook = fragment["payload"]["SessionStart"][0]["hooks"][0]
    assert "env" not in hook


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
@pytest.mark.parametrize(
    ("event", "registration", "stdin_payload"),
    [
        ("SessionStart", 0, {"session_id": "windows-session-smoke"}),
        (
            "UserPromptSubmit",
            0,
            {
                "session_id": "windows-prompt-smoke",
                "prompt": "修复 Windows 安装",
            },
        ),
    ],
)
@pytest.mark.parametrize("launcher_with_spaces", [False, True])
def test_windows_codex_command_executes_through_command_shell(
    tmp_path: Path,
    event: str,
    registration: int,
    stdin_payload: dict[str, str],
    launcher_with_spaces: bool,
) -> None:
    launcher_value = shutil.which("keepygaga")
    assert launcher_value is not None
    launcher = Path(launcher_value).resolve()
    if launcher_with_spaces:
        copied_launcher = tmp_path / "Keepygaga Tool" / "keepygaga.exe"
        copied_launcher.parent.mkdir()
        shutil.copy2(launcher, copied_launcher)
        launcher = copied_launcher
    else:
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
    hook = fragment["payload"][event][registration]["hooks"][0]
    command = hook["command"]
    assert str(config_path.resolve()) not in command
    assert _decoded_config_path(command) == str(config_path.resolve())
    assert "env" not in hook
    assert command.count('"') == (2 if launcher_with_spaces else 0)

    command_shell = os.environ.get("COMSPEC", "cmd.exe")
    codex_command_line = f'{command_shell} /C "{command}"'
    environment = dict(os.environ)
    environment.pop("KEEPYGAGA_CONFIG", None)
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        codex_command_line,
        executable=command_shell,
        check=False,
        capture_output=True,
        encoding="utf-8",
        input=json.dumps(stdin_payload),
        env=environment,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == event
    additional_context = payload["hookSpecificOutput"]["additionalContext"]
    expected = (
        "<keepygaga-bootstrap>" if event == "SessionStart" else "记忆与资料路由规则"
    )
    assert expected in additional_context
