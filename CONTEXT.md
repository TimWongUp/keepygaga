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
三个月后仍应成立的身份级背景 Fact；可包含能改善跨任务交流的职业或长期角色，但不包含项目归属、实现、决策、计划、进度或运行状态。
_Avoid_: 项目档案、项目状态

**Home Page**：
任务开始时必须加载的固定页面，即 `profile.md` 与 `preferences.md`；兼容宿主可直接注入，否则由 Agent 主动读取。
_Avoid_: 动态页摘要、路由目录

**Preference Fact**：
会改变 Agent 回应、工作方式，或表达用户希望在特定任务中考虑哪类长期记忆的稳定 Fact；遗漏它会使跨任务行为持续偏离用户预期。
_Avoid_: 临时要求、宿主协议、工具路由

**Fact Convergence**：
Agent 将候选与目标页 live Facts 比较并判为 covered、refines、new 或 conflict 的写入前分类；Store 不提供语义匹配。
_Avoid_: 自动去重、候选池

**Profile Onboarding**：
首次创建空 `profile.md` 后，由安装 Agent 提供的可跳过画像初始化对话。
_Avoid_: 强制问卷、CLI 交互

**Preference Extraction**：
首次安装时，把目标宿主原有全局规则中的共享软偏好分类并经用户确认后写入 `preferences.md` 的可选流程。
_Avoid_: 全局规则迁移器、自动删除

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
