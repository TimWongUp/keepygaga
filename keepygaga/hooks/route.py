"""Per-turn memory routing reminder and small closeout signal state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from keepygaga.hooks.protocol import additional_context_payload

REMINDER = (
    "按已加载的记忆与资料路由规则，判断本轮是否需要读取、检索或写回；"
    "需要时执行，无需操作时静默继续当前任务，只向用户回复原任务所需内容。"
)
COMPACT_REMINDER = (
    "上下文刚完成压缩。继续任务前，检查是否存在应更新项目长期上下文的稳定结论，"
    "或应登记的长期记忆；有则先完成写入，无则静默继续当前任务，只向用户回复原任务所需内容。"
)
PROJECT_SIGNAL_RE = re.compile(
    r"(?:修改|实现|新增|删除|修复|重构|接入|配置|代码|提交|落地|创建|更新|改造|开发|"
    r"implement|modify|fix|refactor|configure|add|remove|write|build)",
    re.IGNORECASE,
)
MEMORY_SIGNAL_RE = re.compile(
    r"(?:记住|记下来|写入(?:共享)?记忆|更新(?:共享)?记忆|以后(?:请|都|默认)|"
    r"长期(?:规则|偏好)|memory\s*closeout)",
    re.IGNORECASE,
)
STATE_TTL_SECONDS = 24 * 60 * 60


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("content"))
    return ""


def prompt_text(payload: dict[str, Any]) -> str:
    for key in (
        "prompt",
        "user_prompt",
        "userPrompt",
        "user_message",
        "userMessage",
        "message",
        "text",
        "content",
    ):
        text = _text(payload.get(key))
        if text:
            return text
    return ""


def _state_root() -> Path:
    configured = os.environ.get("KEEPYGAGA_HOOK_STATE_ROOT", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path(tempfile.gettempdir()) / "keepygaga-hooks"
    )


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(callable(is_junction) and is_junction())


def _ensure_safe_state_parent(path: Path) -> None:
    current = path.parent
    while current != current.parent:
        if _is_link_like(current):
            raise OSError(f"refusing linked Hook state directory: {current}")
        current = current.parent


def state_path(host: str, payload: dict[str, Any]) -> Path:
    identity = next(
        (
            value
            for key in (
                "session_id",
                "sessionId",
                "conversation_id",
                "conversationId",
                "thread_id",
                "threadId",
                "task_id",
                "taskId",
            )
            if isinstance((value := payload.get(key)), str) and value
        ),
        None,
    )
    if identity is None:
        raise OSError("Hook event has no stable session identity")
    identity_bytes = f"{host}\0{identity}".encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(identity_bytes).hexdigest()[:32]
    return _state_root() / f"{digest}.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or time.time() - float(value.get("updated_at", 0)) > STATE_TTL_SECONDS
        ):
            return None
        return {
            "version": 1,
            "updated_at": float(value.get("updated_at", 0)),
            "project_signal": value.get("project_signal") is True,
            "memory_signal": value.get("memory_signal") is True,
            "reminded": value.get("reminded") is True,
        }
    except (
        FileNotFoundError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return None


def _save(path: Path, value: dict[str, Any]) -> None:
    _ensure_safe_state_parent(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _ensure_safe_state_parent(path)
    if not path.parent.is_dir():
        raise OSError(f"invalid Hook state directory: {path.parent}")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    if _is_link_like(path):
        raise OSError(f"refusing linked Hook state file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.write("\n")
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        if _is_link_like(path):
            raise OSError(f"refusing linked Hook state file: {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def record(host: str, payload: dict[str, Any]) -> None:
    text = prompt_text(payload)
    path = state_path(host, payload)
    if not text:
        previous = _load(path)
        if previous is not None:
            previous["updated_at"] = time.time()
            _save(path, previous)
        return
    _save(
        path,
        {
            "version": 1,
            "updated_at": time.time(),
            "project_signal": bool(PROJECT_SIGNAL_RE.search(text)),
            "memory_signal": bool(MEMORY_SIGNAL_RE.search(text)),
            "reminded": False,
        },
    )


def run(
    host: str, event: str, payload: dict[str, Any], *, compact: bool = False
) -> dict[str, object]:
    with suppress(OSError):
        record(host, payload)
    return additional_context_payload(
        host,
        event,
        COMPACT_REMINDER if compact else REMINDER,
        capability="route",
    )


def consume_closeout(host: str, payload: dict[str, Any]) -> bool:
    path = state_path(host, payload)
    state = _load(path)
    if (
        not state
        or state.get("reminded")
        or not (state.get("project_signal") or state.get("memory_signal"))
    ):
        return False
    state["reminded"] = True
    state["updated_at"] = time.time()
    _save(path, state)
    return True
