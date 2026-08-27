"""Read-only bootstrap of Profile, Preferences, and the live route catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keepygaga.config import load_config
from keepygaga.hooks.protocol import additional_context_payload
from keepygaga.memory import MemoryStore

HOME_PAGES = ("profile.md", "preferences.md")
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
            if basis in {"stated", "observed"} and isinstance(content, str):
                lines.append(f"- [{basis}] {content}")
    return "\n".join(lines)


def load_bootstrap(config_path: Path) -> str:
    config = load_config(config_path)
    if not config.memory.root.strip():
        raise RuntimeError("memory.root is not configured")
    store = MemoryStore(Path(config.memory.root).expanduser(), config.memory)
    listing = store.list_files()
    if listing.get("status") != "ok":
        raise RuntimeError(str(listing.get("message", listing.get("status"))))
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
    raw_listing = listing.get("files")
    route_lines: list[str] = []
    if isinstance(raw_listing, list):
        for item in raw_listing:
            if not isinstance(item, dict) or item.get("path") in HOME_PAGES:
                continue
            path = item.get("path")
            description = item.get("description")
            if not isinstance(path, str) or not isinstance(description, str):
                continue
            aliases = item.get("aliases")
            suffix = (
                f" [aka: {', '.join(aliases)}]"
                if isinstance(aliases, list) and all(isinstance(alias, str) for alias in aliases)
                else ""
            )
            route_lines.append(f"- `{path}` — {description}{suffix}")
    profile = by_path["profile.md"]
    preferences = by_path["preferences.md"]
    return (
        "<keepygaga-bootstrap>\n"
        f"<profile version=\"{profile['version']}\">\n{_facts(profile)}\n</profile>\n\n"
        f"<preferences version=\"{preferences['version']}\">\n{_facts(preferences)}\n</preferences>\n\n"
        "<memory_listing>\n"
        + "\n".join(route_lines)
        + "\n</memory_listing>\n</keepygaga-bootstrap>"
    )


def run(config_path: Path, host: str, event: str, payload: dict[str, Any]) -> dict[str, object]:
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
