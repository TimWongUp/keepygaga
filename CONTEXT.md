# Keepygaga Context

Keepygaga 是面向 Agent 的 local-first 核心记忆系统。这里定义项目特有领域词；行为与精确 schema 以代码和测试为准。

## Language

**核心记忆（Core Memory）**：
跨任务稳定的个人、人物、偏好与持续环境事实集合，由受控 Memory Page 组成。
_Avoid_: 普通知识、RAG、会话历史

**Memory Root**：
由 `memory.root` 配置、直接存放核心记忆页面树的可写本地目录。它可以独立存在，也可以位于 Obsidian Vault 或其他 Markdown 知识库中。
_Avoid_: Obsidian 依赖、数据库目录

**Memory Page**：
`agents-memory/` allowlist 内一份可独立路由和维护的 Markdown 页面。
_Avoid_: 数据库记录、任意 Markdown 文件

**Fact**：
页面内一条带 `stated` 或 `observed` basis、可独立更新或遗忘的完整断言。
_Avoid_: 关键词、最短碎片、推断

**Profile Fact**：
三个月后仍应成立的身份级背景 Fact；可包含能改善跨任务交流的稳定项目归属或长期角色，但不包含项目实现、决策、计划、进度或运行状态。
_Avoid_: 项目档案、项目状态

**项目索引（Project Index）**：
存于直属 `areas/` 页面、用于跨任务定位持续项目并了解重大进展的简短记录。它只包含项目存放位置与已完成的重大里程碑；项目详情、计划与当前状态仍由项目 Authority 或直接真源裁决。
_Avoid_: 状态仪表板、项目日志、项目 Authority 副本

**Route Catalog**：
由 live allowlist 生成的 `path + description + aliases` 路由目录，不包含 Fact 或 version。
_Avoid_: 搜索结果、页面摘要

**Fixed Page**：
不能重命名或整页删除的 `profile.md` 与 `preferences.md`。

**Dynamic Page**：
位于 `topics/`、`areas/` 或 `people/` 直属目录，可显式创建、重命名或删除的页面。

**Version**：
由页面规范化文本派生、写入现有页面时必须携带的 opaque 并发令牌。
_Avoid_: 修订号、数据库版本
