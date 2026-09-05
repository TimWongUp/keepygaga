"""Model-visible payload shapes for supported Agent hook hosts."""

from __future__ import annotations

import json
from typing import Any, Literal


def loads_stdin(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


Capability = Literal["bootstrap", "route", "closeout"]

_PAYLOAD_KINDS: dict[Capability, dict[str, str]] = {
    "bootstrap": {
        "codex": "hook_specific",
        "claude": "hook_specific",
        "workbuddy": "hook_specific",
        "agy_cli": "inject_steps",
        "hermes": "context",
    },
    "route": {
        "codex": "hook_specific",
        "claude": "hook_specific",
        "workbuddy": "hook_specific",
        "agy_cli": "inject_steps",
        "hermes": "context",
    },
    "closeout": {
        "codex": "hook_specific",
        "claude": "hook_specific",
        "workbuddy": "hook_specific",
    },
}

_CLOSEOUT_EVENTS = {
    "codex": "PostToolUse",
    "claude": "PostToolUse",
    "workbuddy": "PostToolUse",
}


def additional_context_payload(
    platform: str,
    event: str,
    context: str,
    *,
    capability: Capability,
) -> dict[str, object]:
    kind = _PAYLOAD_KINDS[capability].get(platform)
    if kind == "hook_specific":
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        }
    if kind == "inject_steps":
        return {"injectSteps": [{"ephemeralMessage": context}]}
    if kind == "context":
        return {"context": context}
    return {}


def closeout_payload(platform: str, context: str) -> dict[str, object]:
    return additional_context_payload(
        platform,
        _CLOSEOUT_EVENTS.get(platform, ""),
        context,
        capability="closeout",
    )
