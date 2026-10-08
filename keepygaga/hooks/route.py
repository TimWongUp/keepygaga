"""Stateless reminders for memory routing and task completion."""

from __future__ import annotations

from keepygaga.hooks.protocol import additional_context_payload

REMINDER = (
    "按已加载的记忆路由规则判断本轮是否需要读取记忆；"
    "完成实质性工作前检查是否需要更新记忆，无需更新时不在回复中提及。"
)
COMPACT_REMINDER = (
    "上下文刚完成压缩。先恢复当前任务目标、用户约束、已完成工作和待办，"
    "沿用已有授权继续推进。完成实质性工作前，按已加载规则检查是否遗漏应维护的稳定项目上下文或用户长期记忆；"
    "需要时核验后更新。压缩本身不构成写入理由，无需更新时不在回复中提及。"
)


def run(host: str, event: str, *, compact: bool = False) -> dict[str, object]:
    return additional_context_payload(
        host, event, COMPACT_REMINDER if compact else REMINDER
    )
