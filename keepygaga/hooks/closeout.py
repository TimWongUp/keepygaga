"""Cross-host closeout reminder with re-entry and per-turn deduplication."""

from __future__ import annotations

from typing import Any

from keepygaga.hooks.protocol import closeout_payload
from keepygaga.hooks.route import consume_closeout

REMINDER = (
    "收尾前按已加载规则检查项目上下文和用户长期记忆；需要则完成更新，"
    "无需更新时静默完成收尾，只向用户回复原任务所需内容。"
)


def run(host: str, event: str, payload: dict[str, Any]) -> dict[str, object]:
    if payload.get("stop_hook_active") or payload.get("stopHookActive"):
        return {}
    if host == "grok":
        return {}
    try:
        return closeout_payload(host, REMINDER) if consume_closeout(host, payload) else {}
    except OSError:
        return {}
