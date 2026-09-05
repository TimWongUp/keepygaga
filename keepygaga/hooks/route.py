"""Stateless reminders for memory routing and task completion."""

from __future__ import annotations

from keepygaga.hooks.protocol import additional_context_payload

REMINDER = (
    "开始本轮任务时，按已加载的记忆与资料路由规则判断是否需要读取记忆或检索资料。"
    "完成前，检查是否产生需要维护的项目上下文或用户长期记忆；需要时按规则核验并更新。"
    "Git 项目进展以规范远端主分支的最新已整合成果及发布状态为准。"
    "无需操作时静默继续，只回复原任务所需内容。"
)
COMPACT_REMINDER = (
    "上下文刚完成压缩。先恢复当前任务目标、用户约束、已完成工作和待办，"
    "沿用已有授权继续推进。按已加载规则检查是否遗漏应维护的稳定项目上下文或用户长期记忆；"
    "需要时核验后更新。压缩本身不构成写入理由，无需更新时静默继续，只回复原任务所需内容。"
)


def run(host: str, event: str, *, compact: bool = False) -> dict[str, object]:
    return additional_context_payload(
        host, event, COMPACT_REMINDER if compact else REMINDER
    )
