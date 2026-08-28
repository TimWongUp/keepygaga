"""Build host-native projections for the three Keepygaga semantic hooks."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from keepygaga.hooks.merge import FRAGMENT_SCHEMA
from keepygaga.host_common import validate_hook_command_path

OWNER = "keepygaga-hook-v1"
USER_HOME = Path.home()
LEGACY_HOOK_RELATIVE_ROOTS = (
    Path("Code/agent-hook-runtime/hooks"),
    Path(".codex/hooks"),
    Path(".claude/hooks"),
    Path(".workbuddy/hooks"),
    Path(".gemini/config/hooks"),
)


def _quote(value: str) -> str:
    return f'"{value}"' if os.name == "nt" else shlex.quote(value)


def _quote_launcher(value: str) -> str:
    if os.name == "nt" and not any(character.isspace() for character in value):
        return value
    return _quote(value)


def _command(
    launcher: Path,
    config_path: Path,
    action: str,
    platform: str,
    event: str,
    *,
    compact: bool = False,
) -> str:
    arguments = [
        str(launcher),
        "--config",
        str(config_path),
        "hook",
        "run",
        action,
        f"--owner={OWNER}",
        "--host",
        platform,
        "--event",
        event,
    ]
    if compact:
        arguments.append("--compact")
    return " ".join(
        _quote_launcher(argument) if index == 0 else _quote(argument)
        for index, argument in enumerate(arguments)
    )


def _entry(command: str, timeout: int, **values: object) -> dict[str, object]:
    return {"type": "command", "command": command, "timeout": timeout, **values}


def build_fragment(
    host: str,
    *,
    launcher: Path,
    config_path: Path,
    enabled: bool = True,
) -> dict[str, Any]:
    validate_hook_command_path(launcher, label="Keepygaga Hook launcher")
    validate_hook_command_path(config_path, label="Keepygaga config path")
    platform = {
        "codex": "codex",
        "claude": "claude",
        "workbuddy": "workbuddy",
        "grok": "grok",
        "hermes": "hermes",
        "antigravity": "agy_cli",
    }.get(host)
    if platform is None:
        raise ValueError(f"unsupported Keepygaga hook host: {host}")

    command_markers: list[str] = []
    legacy_builtin_token_sets = [
        [
            str(launcher),
            "--config",
            str(config_path),
            "hook",
            "run",
            action,
        ]
        for action in ("context", "route", "closeout")
    ]
    legacy_external_token_sets = [
        [str(USER_HOME / root / script), platform]
        for root in LEGACY_HOOK_RELATIVE_ROOTS
        for script in (
            "context_hook.py",
            "memory_route_hook.py",
            "closeout_hook.py",
        )
    ]
    executable_names = {launcher.name, "keepygaga", "keepygaga.exe"}
    owned_command_signatures = [
        [executable, action, f"--owner={OWNER}", platform]
        for executable in sorted(executable_names)
        for action in ("context", "route", "closeout")
    ]
    payload: dict[str, list[dict[str, object]]] = {}
    target = "shared-context-bootstrap" if host == "antigravity" else "hooks"

    if enabled and host == "codex":
        payload = {
            "SessionStart": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "context",
                                platform,
                                "SessionStart",
                            ),
                            10,
                            additionalContextLimit=0,
                        )
                    ]
                },
                {
                    "matcher": "^compact$",
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "route",
                                platform,
                                "SessionStart",
                                compact=True,
                            ),
                            2,
                            additionalContextLimit=180,
                        )
                    ],
                },
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "route",
                                platform,
                                "UserPromptSubmit",
                            ),
                            2,
                            additionalContextLimit=120,
                        )
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "closeout",
                                platform,
                                "PostToolUse",
                            ),
                            2,
                        )
                    ],
                }
            ],
            "SubagentStart": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "context",
                                platform,
                                "SubagentStart",
                            ),
                            10,
                        )
                    ]
                }
            ],
        }
    elif enabled and host == "claude":
        payload = {
            "SessionStart": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "context",
                                platform,
                                "SessionStart",
                            ),
                            10,
                        )
                    ]
                },
                {
                    "matcher": "compact",
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "route",
                                platform,
                                "SessionStart",
                                compact=True,
                            ),
                            2,
                        )
                    ],
                },
            ],
            "SubagentStart": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "context",
                                platform,
                                "SubagentStart",
                            ),
                            10,
                        )
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "route",
                                platform,
                                "UserPromptSubmit",
                            ),
                            2,
                        )
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "closeout",
                                platform,
                                "PostToolUse",
                            ),
                            2,
                        )
                    ],
                }
            ],
        }
    elif enabled and host == "workbuddy":
        payload = {
            "SessionStart": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "context",
                                platform,
                                "SessionStart",
                            ),
                            10,
                        )
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "route",
                                platform,
                                "UserPromptSubmit",
                            ),
                            2,
                        )
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        _entry(
                            _command(
                                launcher,
                                config_path,
                                "closeout",
                                platform,
                                "PostToolUse",
                            ),
                            2,
                        )
                    ],
                }
            ],
        }
    elif enabled and host == "grok":
        payload = {
            "Stop": [
                {
                    "hooks": [
                        _entry(
                            _command(
                                launcher, config_path, "closeout", platform, "Stop"
                            ),
                            2,
                        )
                    ]
                }
            ]
        }
    elif enabled and host == "hermes":
        payload = {
            "pre_llm_call": [
                {
                    "command": _command(
                        launcher, config_path, "context", platform, "pre_llm_call"
                    ),
                    "timeout": 10,
                },
                {
                    "command": _command(
                        launcher, config_path, "route", platform, "pre_llm_call"
                    ),
                    "timeout": 2,
                },
            ],
            "pre_verify": [
                {
                    "command": _command(
                        launcher, config_path, "closeout", platform, "pre_verify"
                    ),
                    "timeout": 2,
                }
            ],
        }
    elif enabled and host == "antigravity":
        payload = {
            "PreInvocation": [
                _entry(
                    _command(
                        launcher, config_path, "context", platform, "PreInvocation"
                    ),
                    10,
                ),
                _entry(
                    _command(launcher, config_path, "route", platform, "PreInvocation"),
                    2,
                ),
            ]
        }

    return {
        "schema": FRAGMENT_SCHEMA,
        "host": host,
        "merge_target": target,
        "owned_command_markers": command_markers,
        "owned_command_token_sets": [
            *legacy_builtin_token_sets,
            *legacy_external_token_sets,
        ],
        "owned_command_suffix_token_sets": [],
        "owned_command_signatures": owned_command_signatures,
        "payload": payload,
    }
