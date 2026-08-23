# Keepygaga Operations

## Verification

按改动风险依次使用：

1. 最接近的 Memory、schema 或 CLI 定向测试。
2. `uv run python scripts/smoke_mcp_server.py` 验证八个 raw Tool、最小 mutation/read 与 Doctor。
3. `uv run pytest -q`。
4. `uv run ruff check . && uv run pyright`。
5. 发行包或入口变化还要运行 `uv build`，在隔离虚拟环境安装生成的 wheel，
   再用 `scripts/smoke_mcp_server.py --server-command <installed keepygaga-mcp>`
   验证已安装的 console script；不能用源码 checkout 遮蔽 wheel，也不能吞掉入口失败。
6. Codex 宿主安装器变化还要在临时 `CODEX_HOME` 运行两次 `keepygaga host setup codex`：第一次完成投影，第二次必须为 `no_op`；验证非空 `AGENTS.override.md` 的优先级、空 override 回退到 `AGENTS.md`、非生效候选的 stale managed block fail closed，以及 Agent Contract 块外原始 bytes、非 Keepygaga MCP 配置和非 AHR Hook 均未变化。确认 apply 顺序为 MCP、rules、可选 hooks，MCP apply 失败时 rules 不写。真实全局配置只在 Tim 明确把当前 Codex 放入目标范围时刷新。

普通验证不修改真实 Vault；测试使用临时 memory tree。当前配置与 live 页面状态必须从 `keepygaga.toml`、Doctor 和目标 Markdown 现场刷新，不能从本文推断。

配置路径优先级固定为显式 CLI `--config`、`KEEPYGAGA_CONFIG`、仓库默认
`keepygaga.toml`。安装与升级验证应显式传入配置绝对路径，MCP 宿主应通过
`KEEPYGAGA_CONFIG` 传入同一文件。

## Doctor semantics

- `ok`：所有适用核心记忆检查正常。
- `warning`：存在需要关注但未阻断的检查；读取具体 check 后再下结论。
- `error`：配置、目录、格式、身份冲突或可写性等直接检查失败。

`memory_tree` 非 `ok` 时，`details.source_status` 保留底层稳定状态；安装程序只在
该值为 `not_initialized` 时调用 `memory init`，不依赖面向用户的 message 文案。

Doctor 只报告非敏感 metadata，不输出正文、凭据、API key、cookie 或 session。公开协议可用性由 MCP smoke 独立验证。

## Failure routing

- 配置加载失败：核对 config path 与 `[memory].root`，示例值不代表本机状态。
- `memory init` 返回 `no_op`：规范树已经完整，命令成功且没有覆盖文件。
- `memory init` 返回 `invalid_source` 或 `invalid_entry`：现有树无效，按 exact path 修正后重新运行 Doctor，不继续补齐。
- `memory init` 返回 `permission_denied`、`write_failed` 或 `partial_commit`：排除目录权限或文件系统问题，核对响应中的已创建文件与目录后重新运行 init 与 Doctor。
- `memory init` 返回 `write_conflict` 或 `not_initialized`：重新运行 Doctor 核对 live tree，再决定是否重试。
- 页面格式无效：停止 mutation，报告 exact path 和错误，保留原文。
- version 冲突：重新 `read` latest，明确合并后重试。
- name 或 alias identity 冲突：修正目标页面或输入，不绕过全库验证。
- `write_failed`：首个文件尚未提交时写入失败；现场未应用本批次内容，排除文件系统问题后重新读取并重试。
- `partial_commit`：响应中的 `applied_paths` 已完成替换，其余路径未完成；重新读取整批相关页面并明确合并，不重复提交原批次，也不假设跨文件回滚。
- `host setup codex` 的 `partial_commit`：响应中的 component 已应用部分必须按其 `backup` / `recovery` 现场处理；MCP 未成功 apply 时 rules 不会写入，rules 成功后 Hook 失败则明确报告已应用的 rules 和未完成的 Hook。
- smoke 失败：先核对 raw Tool 集合与 schema，再进入对应 Store 实现；不以 Doctor 替代协议验证。
- wheel smoke 失败：先区分发行包内容、console script 生成和 MCP 协议失败；源码 smoke
  通过不能替代已安装 artifact 的验证。
- `host setup codex` 报 Agent Contract 标记损坏或重复：保留全局规则现场，人工核对托管块边界后再运行；不得按语义猜测删除规则。
- Codex 全局规则读取按原始 UTF-8 bytes 完成；若规则文件在首次读取后发生变化，setup 以 CAS 冲突失败并保留并发内容。非空 `AGENTS.override.md` 生效，空 override 回退 `AGENTS.md`；生效候选之外已有托管块时停止并人工清理 stale/双入口状态。
- Codex MCP 注册失败：读取 `codex mcp get keepygaga --json`，核对当前 CLI、可执行且能导入 Keepygaga 的 Python 与配置绝对路径。setup 会保留该注册内其他环境变量；`cwd`、`env_vars`、工具筛选或 timeout 等无法由 `codex mcp add` 无损保留的自定义字段存在时 fail closed，先人工决定其归属。发生验证失败时按 `components.mcp.backup` 与 `recovery` 恢复或移除本次新注册；已经成功的规则或 Hook 投影按返回现场处理，修正后幂等重跑 setup。
- Codex Hook setup 跳过：MCP 与规则仍可正常使用；只有明确选择兼容 Agent Hook Runtime、Python 和 runtime root 后才补装。
- Codex Hook setup 失败：从 Agent Hook Runtime 的 Codex fragment、`merge_hook_fragment`、runtime config、`AGENT_HOOK_RUNTIME_CONFIG` / `AGENT_HOOK_RUNTIME_MEMORY_ROOT`、入口脚本和 context smoke 逐层核对；Keepygaga 不内建另一份 Hook payload 作为降级。

## Evidence

测试输出、smoke、Doctor 和原始错误属于 Evidence；分支、进程、端口和一次性实验属于 Run。稳定语义变化更新 `CONTEXT.md`、本目录或 ADR，当前状态不写成长期结论。
