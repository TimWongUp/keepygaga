# Keepygaga Context

Keepygaga 是面向 Agent 的 local-first 核心记忆系统。这里定义项目特有领域词；行为与精确 schema 以代码和测试为准。

## Language

**核心记忆（Core Memory）**：
跨任务稳定的个人、人物、偏好与持续环境事实集合，由受控 Memory Page 组成。
_Avoid_: 普通知识、RAG、会话历史

**Memory Root**：
由 `memory.root` 配置、供所有已接入宿主共用的核心记忆页面树。推荐位于私有 Obsidian Vault，也可以是独立 Markdown 目录。
_Avoid_: 单宿主记忆目录、Obsidian 运行依赖、数据库目录

**人类记忆界面（Human Memory Interface）**：
用户直接查看、纠正和整理 Memory Root 的 Obsidian 或其他 Markdown 编辑器。
_Avoid_: Keepygaga GUI、日常记忆 CLI

**安装与运维控制面（Operations Control Plane）**：
负责安装、宿主接线、状态、诊断、修复、升级与卸载的 `keepygaga` CLI，不承担日常记忆浏览或编辑。
_Avoid_: 记忆管理客户端、Agent 记忆接口

**Memory Page**：
`agents-memory/` allowlist 内一份可独立路由和维护的 Markdown 页面。
_Avoid_: 数据库记录、任意 Markdown 文件

**Fact**：
页面内一条带 Fact Basis、可独立更新或遗忘的完整断言；新写入还带一个 Fact Date。
_Avoid_: 关键词、最短碎片、未标明 basis 的断言

**Fact Basis**：
Fact 的证据类别：`stated` 表示用户明确陈述，`observed` 表示 Agent 从当前可见材料直接归纳或推断。
_Avoid_: 置信度、来源记录、推断等级

**Fact Date**：
Fact 最后一次实际新增或更新的本地日历日期；旧 Fact 可以没有日期。
_Avoid_: 页面修改时间、证据发生时间、有效期

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

**配置级验证宿主（Config-tested Host）**：
适配器的配置投影、保留行为、幂等与失败边界已由仓库测试验证，但尚不据此断言真实客户端会加载该配置。
_Avoid_: 已支持、已验证

**现场验证宿主（Live-verified Host）**：
已在目标宿主的真实 MCP Tool 清单或官方诊断命令中确认当前安装生效的宿主；验证结论只覆盖所记录的宿主版本与环境。
_Avoid_: 仅写入成功、仅临时目录通过

**语义 Hook（Semantic Hook）**：
Keepygaga 自身拥有的 Context Bootstrap、Memory Route 与 Memory Closeout 能力；宿主适配器只负责把能力投影为原生事件和 payload。
_Avoid_: 外部 Hook Runtime、宿主事件名本身

**安装状态（Install State）**：
用于发现已选择宿主、安装渠道和协议版本的本机观察性记录；live 配置与官方诊断始终优先。
_Avoid_: 配置真源、宿主注册 Authority

**稳定启动器（Stable Launcher）**：
随已发布包安装、供宿主长期注册的 `keepygaga-mcp` 与 `keepygaga hook run` 入口。
_Avoid_: checkout 专属 Python 路径、源码目录

**项目真源（Project Authority）**：
能够裁决项目当前事实的直接来源；Git 项目通常使用以 Markdown 自动链接包裹的不带凭据规范远端仓库 URL，例如 `<https://github.com/owner/repo>`，没有持久远端或直接来源时才使用本机路径。
_Avoid_: Memory 摘要、默认本机 checkout、机械采用名为 origin 的任意 fork

**项目索引（Project Index）**：
`areas/projects.md` 中用于跨任务定位持续项目的单页索引；每个项目只有一条 Fact，包含简介、项目真源及可选的最新重大节点，变化时原位更新。
_Avoid_: 多 Fact 项目档案、里程碑历史、状态仪表板、项目真源副本

**Route Catalog**：
由一个 Memory Scope 的 live allowlist 生成的 `path + description + aliases` 路由目录，不包含 Fact 或 version。
_Avoid_: 全库目录、搜索结果、页面摘要

**Memory Scope**：
`topics`、`areas` 或 `people` 中一个有独立路由与页面容量边界的动态页面分区。
_Avoid_: all、搜索范围、任意目录

**动态页整理（Dynamic Page Organization）**：
Agent 在动态页 mutation 需要收敛容量时，先复用语义合适的已有页，必要时创建有稳定主题的新页并原样转移 Facts。
_Avoid_: Store 语义匹配、后台压缩、自动删除

**机械修复（Mechanical Repair）**：
不发明或改变语义内容、且只有一个规范结果的 Memory Page 结构收敛。
_Avoid_: 猜测修复、语义改写、读取时写入

**记忆隐私排除（Memory Privacy Exclusion）**：
禁止写入会直接危及账户、身份或资产的秘密和完整标识，以及用户明确要求不要记住的内容。
_Avoid_: 按健康、财务、政治、宗教、家庭或关系主题一概排除

**Fixed Page**：
不能重命名或整页删除的 `profile.md` 与 `preferences.md`。

**Dynamic Page**：
位于 `topics/`、`areas/` 或 `people/` 直属目录，可显式创建、重命名或删除的页面。

**Version**：
由页面规范化文本派生、写入现有页面时必须携带的 opaque 并发令牌。
_Avoid_: 修订号、数据库版本

**页面快照（Page Snapshot）**：
同一 Memory Page 的内容与匹配 Version 组成的成对视图，用于 Fact Convergence 和条件写入。
_Avoid_: 永远最新的页面、无版本缓存
