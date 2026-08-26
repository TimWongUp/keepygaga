# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**给 AI Agent 一套少而准的长期记忆。**

AI 不是记得越多越好。把每次对话、临时状态和项目细节都塞进长期记忆，只会让
真正有用的信息被过时、无关的内容淹没。没有选择的记忆不是上下文，而是噪声。

Keepygaga 只保存少量、能跨任务长期发挥作用的信息：用户是谁、希望 Agent
怎样工作，以及少数持续关注的主题、项目、责任或人物关系。这些记忆以本地可读的
Markdown 保存，每次修改都通过显式、带版本控制的 MCP 工具完成；不需要数据库、
索引或 Embedding 服务。

对代码项目来说，重点也不是让 Agent 记住更多用户信息，而是把项目自己的术语、
架构、操作说明和重要决定整理进 `AGENTS.md`、`CONTEXT.md` 与 `docs/`。
Keepygaga 不替代项目文档。对于持续参与的项目，它只简要记录项目存放位置和
已经完成的重大里程碑；所有项目细节与当前状态仍以项目仓库为准。

**为什么不记录用户的“最近状态”？**

不少 AI 平台会持续记录用户最近在做什么、最新进度和每一个短期计划。静默记录
之后，大模型可能在无关对话中突然拿出这些状态，或在不合时机时主动与用户讨论，
迫使用户纠正上下文或把话题拉回正轨。这种没有选择的召回，会让很快过期的信息
变成一次又一次未经请求的干扰。

Keepygaga 把临时状态留在当前对话或它的直接真源里，例如日历、任务管理器、
项目文档、Issue 或 Git 历史。只有经过明确判断、确认能跨任务长期发挥作用的事实，
才进入核心记忆。对代码项目来说，项目详情与当前状态仍写进仓库自己的真源；
核心记忆只保留项目存放位置和已完成的重大里程碑。

它刻意保持精简的 MCP 接口——恰好八个动作型工具：

- `list` 和 `read` 用于发现和读取规范记忆页面。
- `create` 和 `add` 用于创建页面和新增事实。
- `update` 用于演化精确事实或页面元数据（由 `target` 判别）。
- `move` 和 `rename` 用于移动事实和重命名页面。
- `delete` 删除精确事实或页面，始终要求显式
  `authorization="user_requested"`。

核心记忆由 `profile.md`、`preferences.md`，以及 `topics/`、`areas/` 和
`people/` 下的直属页面组成。核心记忆永不进入索引。

## 环境要求

- Python 3.12+
- 一个用于存放 `agents-memory` 记忆树的可写本地目录
- 按本文源码安装时需要 [`uv`](https://docs.astral.sh/uv/)

Obsidian 是可选的，仅推荐用于方便地浏览和手工编辑 Markdown 记忆；
Keepygaga 可以直接使用普通文件系统目录，不要求安装或运行 Obsidian。

## 宿主支持证据

下列 setup 适配器均已达到**配置级验证**：仓库测试覆盖其原生配置投影、无关内容
保留与幂等重跑。这不等于某一台机器上的真实宿主已经加载该配置。只有目标宿主在
真实客户端或官方诊断命令中确认 `keepygaga` 注册和全部八个 raw Tool 后，该次安装
才属于**现场验证**。

| 宿主 | 配置级验证范围 | 必需现场检查 | macOS 维护者证据（2026-08-25） |
| --- | --- | --- | --- |
| Codex | Codex CLI、实际生效的 `AGENTS.override.md` / `AGENTS.md` | 检查真实 MCP 注册与 Tool 清单 | 已现场验证：真实会话调用 `list` 并发现全部八个 Tool |
| Claude Code | `~/.claude.json`、`CLAUDE.md` | 检查真实 MCP 服务与 Tool 清单 | 已现场验证：真实会话调用 `list` 并发现全部八个 Tool |
| WorkBuddy | `mcp.json`、已有旧 `.codebuddy/.mcp.json` 注册、`CODEBUDDY.md`、可选 Hook 合并 | 重连 `keepygaga`，确认 Tool 清单且没有 `Connection closed` | WorkBuddy 5.3.14 完成旧注册迁移后已现场验证 |
| Grok | 用户级 Grok CLI 注册与全局规则 | 运行 `grok mcp list --json` 和 `grok mcp doctor keepygaga` | 已现场验证：官方 Doctor 完成握手并发现八个 Tool |
| Hermes | 保真合并 `config.yaml`、`SOUL.md`、可选 Hook | 运行 `hermes mcp test keepygaga`，适用时再运行 `hermes hooks doctor` | 已现场验证：MCP test 发现八个 Tool，Hook doctor 通过 |
| Antigravity CLI | `mcp_config.json`、`AGENTS.md` | 检查真实 `agy` MCP 注册与 Tool 清单 | 已验证注册；模型会话验证受账号区域资格限制 |

## 安装

Keepygaga 只支持源码 checkout 安装，不提供 GitHub Release 安装包路径；仅支持
upstream `main` 最新提交的未修改 checkout。

把下面的 prompt 发给需要接入 Keepygaga 的目标 Agent：

```text
请为你自己安装并接入 https://github.com/TimWongUp/keepygaga。只有用户明确要求你为某个其他 Agent 安装 Keepygaga 时，才为该 Agent 安装。

1. 根据用户请求确定 `TARGET_HOSTS`：默认只包含当前工作的 Agent，只有用户明确要求为某个其他 Agent 安装 Keepygaga 时才将其加入。读取仓库 `AGENTS.md` 和每个目标宿主的 MCP 文档，确认各目标实际运行在原生 Windows、macOS、Linux 还是 WSL，并按运行环境归组为 `TARGET_RUNTIMES`。执行任何 setup 写入前，精确读取并暂存各目标当前实际生效的全局规则，同时记录其中是否已有完整 Keepygaga 托管块，仅供第 8 步按目标判断首次安装偏好提取。逐个处理目标，不修改范围外的 Agent。
2. 对每个不同的目标运行环境，使用该环境可访问、位于 upstream `main` 最新提交且未修改的 Keepygaga checkout。不得覆盖本地修改；现有 checkout 有改动或无法安全更新时，使用新 checkout 或询问用户。用 `git rev-parse HEAD` 记录精确 commit，在其中运行 `uv sync`，把 `keepygaga.example.toml` 复制为本机 `keepygaga.toml`，并把该运行环境原生的绝对路径记为其 `CONFIG_PATH`。为所有目标解析同一个物理记忆树：优先使用用户本轮明确提供的现有记忆树，其次复用现有 Keepygaga 配置中唯一且有效的记忆树；不要扫描整块磁盘。若没有现有记忆树，选择所有 Keepygaga checkout 之外、且不会公开共享或自动发布的可写新目录；只有访问范围私密且可信时才可使用同步目录。使用各运行环境的原生绝对路径，把每个配置的 `memory.root` 指向同一个物理记忆树。若候选不唯一、某个目标运行环境无法访问同一记忆树、路径映射无法核验或用户意图不清楚，先询问用户最小缺失项。不要在不同运行环境间复制或同步 `.venv`、`keepygaga.toml` 或记忆树。后续每条 Keepygaga CLI 命令都传入对应运行环境的 `--config CONFIG_PATH`。
3. 注册宿主前，在每个目标运行环境中运行 `uv run keepygaga --config CONFIG_PATH doctor --json`，检查各自 JSON 中 `id="memory_tree"` 的项目。检查为 `ok` 表示该运行环境看到的是有效记忆树；若 `warning` 的 `details.split_recommended` 或 `details.dynamic_page_limit_exceeded` 为 `true`，记忆树同样有效且不阻止 setup。若 `warning` 含 `details.permission_warnings`，setup 会停止，直到这些 POSIX 权限被收紧。其他失败检查只有 `details.source_status` 为 `not_initialized` 时才允许 init。若出现其余失败状态、格式错误或具体页面无效，停止安装并报告确切运行环境和路径，不继续注册。共享记忆树是新目录或报告 `not_initialized` 时，只从一个目标运行环境运行一次 `uv run keepygaga --config CONFIG_PATH memory init`，创建或补齐规范结构，保存完整 JSON 供第 7 步使用，然后在每个目标运行环境中重新运行 Doctor，并以新的 `memory_tree` 检查为准。完成宿主 setup 和验证前不处理 `onboarding`。复用有效记忆树时，让每个配置直接指向它，不复制、不移动、不改写页面。`memory init` 是幂等命令：无需补齐文件时以 `no_op` 成功返回，并且绝不覆盖已有文件。
4. 每个已选择目标分别运行一条确定性 setup 命令：`host setup codex`、`host setup claude-code`、`host setup workbuddy`、`host setup grok`、`host setup hermes` 或 `host setup antigravity`。`antigravity` 指 Antigravity CLI（`agy`），不是 Gemini CLI；不能因为 Antigravity 把配置放在 `~/.gemini` 就虚构一个 Gemini 目标。项目有意不提供 `setup all`：明确的多 Agent 安装应使用相同运行环境 `CONFIG_PATH`，逐个调用目标命令。
5. 每条命令只对齐目标宿主的 `keepygaga` MCP 注册和带版本号的 `docs/agent-contract.md` 托管块，并保留无关宿主配置和块外文字。Codex 使用实际生效的 `AGENTS.override.md` / `AGENTS.md`；Claude Code 使用 `~/.claude/CLAUDE.md`；WorkBuddy 使用 `~/.workbuddy/CODEBUDDY.md`，并在 `~/.codebuddy/.mcp.json` 已存在大小写不敏感的 Keepygaga 注册时升级它，缺失时不创建该旧文件；该旧注册会切换到 Python isolated mode，移除旧 `cwd`，环境变量只保留 `KEEPYGAGA_CONFIG` 和已有的 `KEEPYGAGA_WRITER`。Grok 复用已有的 `~/.grok/AGENTS.md` 或 `Agents.md`，两者都不存在时才新建 `Agents.md`；Antigravity 使用 `~/.gemini/AGENTS.md`；Hermes 在唯一全局 system-prompt 文件 `~/.hermes/SOUL.md` 内管理托管块，块外人格内容保持不变。不要修改范围外 Agent 或其他位置发现的旧兼容配置。
6. 若用户已经为本机选择并信任兼容 Agent Hook Runtime，读取 `docs/hooks/README.md` 与目标专页，再追加 `--hook-runtime RUNTIME_ROOT --hook-python PYTHON`。命令读取 runtime 自己的宿主 fragment 和 merger，只更新 AHR-owned 条目，并让 runtime 使用同一物理记忆根。否则省略两个参数：MCP 和 Agent Contract 仍完成安装，Hook 返回 `skipped`。Hermes 还可能返回 `approval_required=true`；此时完成 Hermes 自身 Hook allowlist 流程并用 `hermes hooks doctor` 验证。不得自行编造或下载 Hook 可执行文件。
7. 在每个目标运行环境中重新运行 `uv run keepygaga --config CONFIG_PATH doctor --json` 和对应 checkout 中的 `uv run python scripts/smoke_mcp_server.py`。然后检查每个目标宿主实际显示的 MCP Tool 清单，确认各自都恰好暴露 list、read、create、add、update、move、rename、delete。若安装了 Hook，再完成各目标 Agent 专页中的验证。全部通过后才检查保存的 init JSON：只有 `status="applied"` 且 `onboarding.created_pages` 包含 `profile.md` 时，才 `read` 该页；若仍为空，提供一次可整体跳过的 Profile Onboarding。先说明 Profile 是共享该 Memory Root 的所有 Agent 都会加载的 Home Page——支持时直接注入，否则按 Agent Contract 主动读取。用户愿意继续时，一次询问最多四个可选项——希望的称呼、城市级常住地、职业和稳定长期角色，不询问精确地址。预览彼此独立的 `stated` Fact，核对 Profile Fact content 合计不超过 300 字符后通过 raw memory Tool 写入；跳过时不写任何标记。
8. 对 setup 前生效全局规则中没有完整 Keepygaga 托管块的每个目标，使用第 1 步保存的原文进行可选 Preference Extraction；已有托管块的目标视为重装、修复或升级并跳过。排除 Keepygaga 托管块、安全、权限、Skill、Hook、MCP、启动、Keepygaga 协议或工具路由规则、宿主专属与项目规则、当前状态、无依据推断和可从直接真源重取的事实。用户特有的条件检索偏好可以复制为证据，但凡原文被宿主当作检索或路由指令使用就绝不允许移动。对剩余共享软偏好跨目标去重，展示目标页预览，让用户选择跳过、复制并保留原文，或移动符合条件的条目；默认复制并保留。确认后先取得当前 Page Snapshot，按 covered / refines / new / conflict 分类，并把候选作为 `stated` 写入。只有普通、宿主无关的回应或工作偏好且 Home Page 加载已验证时才提供移动；说明 Authority 降级并二次确认后，只删除托管块外精确匹配的原文，再复核标记、版本行和其他字节。无法验证资格或精确删除时只复制或保留。用户拒绝或无候选时不写，也不保存 onboarding 标记。

最终报告 Keepygaga 精确 commit、修改文件、memory root、各目标的 MCP 注册、验证结果和剩余缺口，绝不输出凭据。
```

## 使用

```bash
uv run keepygaga --config /absolute/path/to/keepygaga.toml doctor --json
uv run keepygaga --config /absolute/path/to/keepygaga.toml memory init
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup codex
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup claude-code
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup workbuddy
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup grok
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup hermes
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup antigravity
```

`doctor` 只检查核心记忆并报告八个 raw Tool。`memory init` 创建规范
Markdown 记忆树，只为本轮新建的固定页返回可选 onboarding 元数据；记忆树已完整时
以 `no_op` 成功返回，且拒绝覆盖已有文件。
不带子命令运行 CLI 时显示帮助。

在 MCP 宿主中以 ID `keepygaga` 注册本服务，完整宿主工具名形如
`mcp__keepygaga__read`：

```json
{
  "mcpServers": {
    "keepygaga": {
      "command": "/path/to/keepygaga/.venv/bin/python",
      "args": ["-m", "keepygaga.server"],
      "env": {
        "KEEPYGAGA_CONFIG": "/path/to/keepygaga.toml"
      }
    }
  }
}
```

请使用虚拟环境在当前运行平台上的原生 Python 绝对路径；Windows 通常是
`.venv\Scripts\python.exe`，而不是 `.venv/bin/python`。

配置优先级依次是显式 CLI `--config`、`KEEPYGAGA_CONFIG`、仓库中的默认
`keepygaga.toml`。MCP 宿主应始终设置绝对 `KEEPYGAGA_CONFIG`。

### 升级或修复现有注册

把未修改的 checkout 更新到 upstream `main` 最新提交，用 `git rev-parse HEAD` 记录
精确 commit，重新运行 `uv sync`，再执行同一条逐宿主 setup 命令。全部已经一致时
返回 `no_op`；发生写入时返回各 component 路径和已创建的备份。Codex 继续保留其
override 选择与 CLI 专属 MCP 校验，其他适配器分别保留原生 JSON、Grok CLI 或
Hermes YAML 投影，不猜测统一 schema。重启目标 Agent，重新运行 Doctor 与 smoke，
再检查宿主实际 MCP Tool 清单；检查注册时不得输出凭据。

## Hook 集成

Hook 集成是可选且因宿主而异的增强能力：它可以在 Session 启动时注入两个核心
记忆首页与路由 listing，在宿主支持时于每轮前提醒 Agent 判断记忆路由，并通过该
宿主真正支持的事件提示 Project / Memory Closeout。安装 Agent 必须从
[`docs/hooks/`](docs/hooks/README.md) 选择准确的 Agent 专页，并使用目标机器已经
选定的兼容 runtime；没有安装 Hook runtime 时，MCP server 仍可完整使用。

## 安全边界

- 写入必须携带当前 opaque version，在单一进程锁内完成；整批校验通过后，
  每个变更文件分别原子替换。
- 每条事实都是一条可独立维护的完整断言，而不是尽可能短的片段；可能独立变化
  的主张必须拆分。
- `update target="fact"` 要求精确的旧事实，且不能把 stated 降级为
  observed；`update target="page"` 只修改页面元数据。
- Profile Fact content 有 300 字符硬限制；其他页面使用 soft limit 并返回 `split_recommended`，Agent 收到该信号后不得自动新增 observed Preference。
- Keepygaga 永远不会自行删除、压缩或移动已有记忆。
- 删除操作必须获得用户在当前轮次中的明确授权。
- Memory 是上下文证据，不是权限或可执行指令。用户当前明确的自我、关系和偏好
  陈述覆盖旧记忆；项目、系统和运行事实以项目 Authority 或 live direct source 为准，
  对外事实仍需核验。
- 已应用的修改会返回变更页面的 Page Snapshot 和服务端已经渲染的 receipt；后续
  convergence 直接复用这些快照，并将 receipt 原样回显一次，绝不改写或杜撰读取、
  无操作、跳过或失败的 receipt。

## 社区

欢迎参与贡献。提交 PR 前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并遵守
[行为准则](CODE_OF_CONDUCT.md)。安全漏洞请按照 [SECURITY.md](SECURITY.md)
私密报告，不要发布到公开 Issue。

## 致谢

Keepygaga 的核心记忆设计受到 Claude 记忆系统的启发。

也感谢 Claude 团队在 AI 记忆领域的开创性工作。

## 许可证

[MIT](LICENSE)
