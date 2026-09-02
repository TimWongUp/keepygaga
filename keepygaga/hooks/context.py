"""Read-only bootstrap of Home Pages and bounded memory-scope descriptions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keepygaga.config import load_config
from keepygaga.hooks.protocol import additional_context_payload
from keepygaga.memory import MemoryStore

HOME_PAGES = ("profile.md", "preferences.md")
SCOPE_DESCRIPTIONS = {
    "topics": "长期主题、偏好对象与个人生活信息；需要相关记忆时调用 list(scope=topics)。",
    "areas": "持续活动、环境与项目索引；需要相关记忆时调用 list(scope=areas)。",
    "people": "已知人物及与用户的关系上下文；涉及具体人物时调用 list(scope=people)。",
}
CODEX_SUBAGENT_CONTEXT = (
    "仅在任务需要长期上下文时，按全局规则中的记忆路由读取对应页；不要预加载无关记忆。"
)


def _facts(item: dict[str, Any]) -> str:
    facts = item.get("facts", [])
    if not isinstance(facts, list):
        return ""
    lines = []
    for fact in facts:
        if isinstance(fact, dict):
            basis = fact.get("basis")
            content = fact.get("content")
            fact_date = fact.get("date")
            if basis in {"stated", "observed"} and isinstance(content, str):
                suffix = f" [{fact_date}]" if isinstance(fact_date, str) else ""
                lines.append(f"- [{basis}] {content}{suffix}")
    return "\n".join(lines)


def load_bootstrap(config_path: Path) -> str:
    config = load_config(config_path)
    if not config.memory.root.strip():
        raise RuntimeError("memory.root is not configured")
    store = MemoryStore(Path(config.memory.root).expanduser(), config.memory)
    read = store.read(list(HOME_PAGES))
    if read.get("status") != "ok":
        raise RuntimeError(str(read.get("message", read.get("status"))))
    raw_files = read.get("files")
    if not isinstance(raw_files, list):
        raise RuntimeError("home-page read returned no files")
    by_path = {
        item["path"]: item
        for item in raw_files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if any(path not in by_path for path in HOME_PAGES):
        raise RuntimeError("home-page read is incomplete")
    profile = by_path["profile.md"]
    preferences = by_path["preferences.md"]
    scope_lines = [
        f"- `{scope}` — {description}"
        for scope, description in SCOPE_DESCRIPTIONS.items()
    ]
    return (
        "<keepygaga-bootstrap>\n"
        f'<profile version="{profile["version"]}">\n{_facts(profile)}\n</profile>\n\n'
        f'<preferences version="{preferences["version"]}">\n{_facts(preferences)}\n</preferences>\n\n'
        "<memory_scopes>\n"
        + "\n".join(scope_lines)
        + "\n</memory_scopes>\n</keepygaga-bootstrap>"
    )


def run(
    config_path: Path, host: str, event: str, payload: dict[str, Any]
) -> dict[str, object]:
    actual_event = next(
        (
            value
            for key in ("hook_event_name", "hookEventName")
            if isinstance((value := payload.get(key)), str) and value
        ),
        event,
    )
    if host == "codex" and actual_event == "SubagentStart":
        context = CODEX_SUBAGENT_CONTEXT
    else:
        try:
            context = load_bootstrap(config_path)
        except Exception as exc:
            context = (
                "<keepygaga-bootstrap-error>\n"
                f"动态注入失败：{exc}。不要用猜测或其他检索替代；向用户报告该错误。\n"
                "</keepygaga-bootstrap-error>"
            )
    return additional_context_payload(
        host, actual_event, context, capability="bootstrap"
    )


def loads_stdin(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
