# Keepygaga Agent Entry

## Scope and authority

- Keepygaga 是独立的 Agent 核心记忆仓库；Knowledge/RAG 属于 sibling repo `keepygaga-knowledge`，两者不得建立 Python 运行依赖。
- Vault `agents-memory/` Markdown 是唯一核心记忆真源；代码、MCP schema 和测试裁决当前行为。
- `README.md` 面向首次使用者，不是 agent 默认项目真源。

## Repo-native context

- 讨论领域词或页面/Fact 边界时读 `CONTEXT.md`。
- 修改核心记忆模型、Tool 语义、version、写入不变量或宿主集成时读 `docs/architecture.md`。
- 修改验证、Doctor、smoke、失败分流或证据路由时读 `docs/operations.md`。
- 修改宿主长期记忆规则时读 `docs/agent-contract.md`。
- 安装或修复宿主 Hook 接线时先读 `docs/hooks/README.md`，再只读目标 Agent 对应专页；没有兼容 runtime 时只完成 MCP 安装并明确报告，不生成临时 Hook 实现。
- 追溯拆仓或动作型 MCP Tool 名的理由时读 `docs/adr/`；ADR 不覆盖当前代码与测试。
- 长期上下文只在本 repo 维护；Vault 中已退役的旧项目上下文只作历史归档，不能成为当前 Authority。

## Project constraints

- Python `3.12+`；优先使用 repo `.venv/`。
- 产品、发行包、Python 包、CLI、配置、环境变量、schema 与代码标识统一使用 Keepygaga / `keepygaga`；MCP 客户端配置约定使用注册 key `keepygaga`，它不等同于 FastMCP `serverInfo.name`。
- 公开 raw MCP Tool 必须且只能是 `list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`；不保留旧 `memory_*` 或 Knowledge Tool 别名。
- `update` 与 `delete` 使用 `target=fact|page` 判别式操作；`delete` 只在当前用户当轮明确授权后调用并要求 `authorization=user_requested`。
- 固定页只有 `profile.md` 与 `preferences.md`；动态页只允许 `topics/*.md`、`areas/*.md`、`people/*.md` 的直属 Markdown。
- 规范 frontmatter 固定为 `name`、`description`、`aliases`；正文只允许单行 `- [stated|observed]` Fact。读取兼容带 `sources` 的旧页面，下一次 mutation 将其规范化。
- `contracts/core-memory-v1/` 是宿主注入器的版本化 consumer contract；页面格式变化必须同步 fixture，并由本仓测试裁决 parser/renderer 与 fixture 一致。
- Fact 是可独立维护的完整断言。写入先判定 covered / refines / new / conflict：covered 不写，refines 用 `update`，new 用 `add`，conflict 先按当前用户陈述或直接证据核对。
- `profile.md` 只保存三个月后仍应成立的身份与背景；能改善跨任务交流的稳定项目归属或长期角色可进入 Profile，项目实现、决策、计划、进度和运行状态留在项目 Authority 或 `areas/`。Profile Fact content 合计不超过 300 字符；`preferences.md` 只保存当前用户希望 Agent 如何回应和工作的长期偏好。
- 每次 list/read/mutation 都重新读取 live Markdown；旧 version 必须冲突，mutation 在全局锁内完成整批预检并逐文件原子替换。跨文件崩溃原子性不属于合同；格式无效时 fail closed 并保留现场。
- Memory Tool 不做语义匹配、自动删除、压缩、拆分、转移或候选提升；不恢复旧 `USER.md`、`ENVIRONMENT.md`、`user/`、`active/`、`history/`、`review/` 或 `archive/` 结构。
- `keepygaga.toml` 与 `.venv/` 是本机产物，不提交；密钥不得进入日志、Doctor、文档或测试 fixture。

## Commands and verification

- 安装：`uv sync`
- 默认验收：`uv run python scripts/smoke_mcp_server.py`
- 测试：`uv run pytest -q`
- 静态检查：`uv run ruff check . && uv run pyright`
- 诊断：`uv run keepygaga doctor --json`
- 初始化：`uv run keepygaga memory init`
- 必需检查无法运行时，报告命令、阻塞和剩余不确定性。

## Context change gate

- Run 不进入长期上下文；Artifact 留在代码、schema、配置和测试；Evidence 保留原始输出或可复现命令。
- 稳定领域词更新 `CONTEXT.md`；核心记忆语义、不变量、所有权和集成边界更新 `docs/architecture.md`；验证策略与证据路由更新 `docs/operations.md`；符合门槛的难改取舍写入 `docs/adr/`。
- 精确参数、schema 与当前运行状态留在代码、测试、配置和现场系统，不复制进长期上下文。
