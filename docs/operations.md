# Keepygaga Operations

## Verification

按改动风险依次使用：

1. 最接近的 Memory、schema 或 CLI 定向测试。
2. `uv run python scripts/smoke_mcp_server.py` 验证八个 raw Tool、最小 mutation/read 与 Doctor。
3. `uv run pytest -q`。
4. `uv run ruff check . && uv run pyright`。
5. Codex 宿主安装器变化还要在临时 `CODEX_HOME` 运行两次 `keepygaga host setup codex`：第一次完成投影，第二次必须为 `no_op`；验证非空 `AGENTS.override.md` 的优先级、空 override 回退到 `AGENTS.md`、非生效候选的 stale managed block fail closed，以及 Agent Contract 块外原始 bytes、非 Keepygaga MCP 配置和非 AHR Hook 均未变化。确认 apply 顺序为 MCP、rules、可选 hooks，MCP apply 失败时 rules 不写。真实全局配置只在 Tim 明确把当前 Codex 放入目标范围时刷新。
6. 非 Codex 宿主适配器变化在临时 host home 分别运行两次对应 `host setup`：第一次只更新 `keepygaga` MCP、Agent Contract 托管块和选中的 AHR-owned Hook，第二次必须为 `no_op`；核对无关 MCP、全局规则块外内容和其他 Hook 仍在。WorkBuddy 还要覆盖同级 `.codebuddy/.mcp.json` 已有 `Keepygaga` 旧注册的规范化、禁用状态与块外配置保留、缺失时不创建、旧 `cwd` 与非 Keepygaga 环境变量移除、Python isolated mode、原始 JSON 重复键、大小写重复注册、prepare/apply 漂移、symlink 与 Windows junction 拒绝；真实客户端需确认当前公开 raw Tool 均已发现且未出现 `Connection closed`，旧注册存在并完成迁移时再用内置 `codebuddy mcp get keepygaga` / `mcp list` 核对该兼容入口。临时 host home 只能验证写入与幂等，不能证明 WorkBuddy 实际读取了该配置文件。Grok 额外用 `grok mcp list --json` / `grok mcp doctor keepygaga` 核对用户层注册；Hermes 额外用 `hermes mcp test keepygaga` 与 `hermes hooks doctor` 核对 YAML 投影和 Hook allowlist；Antigravity 只使用 `antigravity` 适配器与 `agy` 现场验证，不把 `~/.gemini/settings.json` 当作 Gemini CLI 接线。
7. 非 Codex 适配器的配置级验收还必须覆盖损坏 JSON/YAML、符号链接目标、重复托管块、写入冲突或 partial commit，以及宿主不匹配 CLI 参数；这些测试通过后只能记为 Config-tested。只有目标真实客户端或官方诊断确认当前安装的注册与八个 Tool 后，才能把该环境记为 Live-verified。

普通验证不修改真实 Vault；测试使用临时 memory tree。当前配置与 live 页面状态必须从 `keepygaga.toml`、Doctor 和目标 Markdown 现场刷新，不能从本文推断。

配置路径优先级固定为显式 CLI `--config`、`KEEPYGAGA_CONFIG`、仓库默认
`keepygaga.toml`。安装与升级验证应显式传入配置绝对路径，MCP 宿主应通过
`KEEPYGAGA_CONFIG` 传入同一文件。

## First-install onboarding

安装 Agent 在运行 `memory init` 时保存完整 JSON，但要等 MCP、Agent Contract 与可选 Hook 验证成功后才处理 `onboarding`。只有 `status="applied"` 且 `onboarding.created_pages` 包含 `profile.md`，并经 `read` 确认该页为空时，才提供一次可整体跳过的 Profile Onboarding；`no_op`、失败、partial commit，或只新建 `preferences.md` 时不启动 Profile 问答。

开始前告知用户：Profile 是共享该 Memory Root 的目标 Agent 都会加载的 Home Page；兼容宿主直接注入，其他宿主按 Agent Contract 主动读取。用户愿意继续时，一次性询问最多四个可选项：希望的称呼、城市级常住地、职业，以及有长期交流价值的稳定角色；不询问精确地址，每项都可跳过。把回答整理为彼此独立的 `stated` Fact，写入前预览并核对 Profile Fact content 合计不超过 300 字符，再通过 raw `list`、`read` 与一次 `add` 写入。跳过时不写标记，不在后续 `memory init no_op` 时重复触发。

## Preference extraction

Preference Extraction 按目标宿主判断首次安装。任何 setup 写入前先只读保存各目标宿主实际生效的原有全局规则，并记录其中是否已有完整 Keepygaga 托管块；只有没有托管块的目标进入 Extraction，有块的重装、修复或升级直接跳过。候选只来自这些 setup 前原文，不来自本轮合并的托管块或安装指令。逐条分类为共享软偏好、宿主专属规则、安全/权限/启动/Keepygaga 协议或工具路由规则、项目规则或不写；只有遗漏会持续改变 Agent 回应、工作方式或用户希望考虑哪类长期记忆的共享软偏好可进入 `preferences.md`。

先展示去重后的候选及写入预览，让用户选择跳过、复制并保留原文，或移动符合条件的候选。默认是复制并保留原文。用户特有的条件检索偏好可以复制为证据，但凡原文被宿主当作检索或路由指令使用就不得移动。移动只适用于不承担安全、权限、Skill、Hook、MCP、检索、路由或启动职责的普通跨宿主回应/工作偏好，并要求当前目标宿主已现场验证 Home Page 加载、用户看过 Authority 降级说明并再次确认。删除只针对当前生效规则文件中托管块外的精确原文；修改后重新验证 Keepygaga 标记、版本行和其他字节。条件不满足、规则混合承载职责或无法精确定位时只复制或保留，不猜测删除。

确认写入后先 `read preferences.md`，按 Fact Convergence 分类；用户确认的候选以 `stated` 写入。已有页面返回 `split_recommended` 时仍允许用户明确要求的 stated 写入，但必须先提示首页预算。该流程不写 onboarding 标记，也不由 `host setup`、Store 或 Hook 自动执行。

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
- version 冲突：响应含 `latest` 时直接将其作为 Page Snapshot 重新分类；缺少 `latest` 时才重新 `read`，明确合并后使用新 version 重试，不原样重试旧 operation。
- name 或 alias identity 冲突：修正目标页面或输入，不绕过全库验证。
- `write_failed`：首个文件尚未提交时写入失败；现场未应用本批次内容，排除文件系统问题后重新读取并重试。
- `partial_commit`：响应中的 `applied_paths` 已完成替换，其余路径未完成；重新读取整批相关页面并明确合并，不重复提交原批次，也不假设跨文件回滚。
- `host setup codex` 的 `partial_commit`：响应中的 component 已应用部分必须按其 `backup` / `recovery` 现场处理；MCP 未成功 apply 时 rules 不会写入，rules 成功后 Hook 失败则明确报告已应用的 rules 和未完成的 Hook。
- 任一非 Codex `host setup` 的 `partial_commit`：以返回的 `components`、`path` 与 `backup` 为现场，不假设不同宿主配置能够统一回滚；核对后幂等重跑同一个宿主。Hermes 首次写入 AHR Hook 后若 `approval_required=true`，由用户明确选择的 runtime 仍需通过 Hermes 自身 Hook allowlist，再用 `hermes hooks doctor` 验证。
- WorkBuddy 旧配置迁移失败：保留 `~/.workbuddy/mcp.json` 与 `~/.codebuddy/.mcp.json` 现场，按 `mcp`、`legacy_mcp` component 的状态和备份处理；旧文件存在多个大小写不同的 Keepygaga 键时先人工收敛为一个，缺失旧文件时不得为兼容性新建。
- smoke 失败：先核对 raw Tool 集合与 schema，再进入对应 Store 实现；不以 Doctor 替代协议验证。
- `host setup codex` 报 Agent Contract 标记损坏或重复：保留全局规则现场，人工核对托管块边界后再运行；不得按语义猜测删除规则。
- Codex 全局规则读取按原始 UTF-8 bytes 完成；若规则文件在首次读取后发生变化，setup 以 CAS 冲突失败并保留并发内容。非空 `AGENTS.override.md` 生效，空 override 回退 `AGENTS.md`；生效候选之外已有托管块时停止并人工清理 stale/双入口状态。
- Codex MCP 注册失败：读取 `codex mcp get keepygaga --json`，核对当前 CLI、可执行且能导入 Keepygaga 的 Python 与配置绝对路径。setup 会保留该注册内其他环境变量；`cwd`、`env_vars`、工具筛选或 timeout 等无法由 `codex mcp add` 无损保留的自定义字段存在时 fail closed，先人工决定其归属。发生验证失败时按 `components.mcp.backup` 与 `recovery` 恢复或移除本次新注册；已经成功的规则或 Hook 投影按返回现场处理，修正后幂等重跑 setup。
- Codex Hook setup 跳过：MCP 与规则仍可正常使用；只有明确选择兼容 Agent Hook Runtime、Python 和 runtime root 后才补装。
- Codex Hook setup 失败：从 Agent Hook Runtime 的 Codex fragment、`merge_hook_fragment`、runtime config、`AGENT_HOOK_RUNTIME_CONFIG` / `AGENT_HOOK_RUNTIME_MEMORY_ROOT`、入口脚本和 context smoke 逐层核对；Keepygaga 不内建另一份 Hook payload 作为降级。

## Evidence

测试输出、smoke、Doctor 和原始错误属于 Evidence；分支、进程、端口和一次性实验属于 Run。稳定语义变化更新 `CONTEXT.md`、本目录或 ADR，当前状态不写成长期结论。
