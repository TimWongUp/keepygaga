"""Model-visible payload shapes for supported Agent hook hosts."""

from __future__ import annotations

import json
from typing import Any


def loads_stdin(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


_PAYLOAD_KINDS = {
    "codex": "hook_specific",
    "claude": "hook_specific",
    "workbuddy": "hook_specific",
    "agy_cli": "inject_steps",
    "hermes": "context",
}


def additional_context_payload(
    platform: str,
    event: str,
    context: str,
) -> dict[str, object]:
    kind = _PAYLOAD_KINDS.get(platform)
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
