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

## 安装

把下面的 prompt 发给需要接入 Keepygaga 的目标 Agent：

```text
请为你自己安装并接入 https://github.com/TimWongUp/keepygaga。只有用户明确要求你为某个其他 Agent 安装 Keepygaga 时，才为该 Agent 安装。

1. 根据用户请求确定 `TARGET_HOSTS`：默认只包含当前工作的 Agent，只有用户明确要求为某个其他 Agent 安装 Keepygaga 时才将其加入。读取仓库 `AGENTS.md` 和每个目标宿主的 MCP 文档，确认各目标实际运行在原生 Windows、macOS、Linux 还是 WSL，并按运行环境归组为 `TARGET_RUNTIMES`。执行任何 setup 写入前，精确读取并暂存各目标当前实际生效的全局规则，同时记录其中是否已有完整 Keepygaga 托管块，仅供第 8 步按目标判断首次安装偏好提取。逐个处理目标，不修改范围外的 Agent。
2. 对每个不同的目标运行环境，使用该环境可访问的 Keepygaga checkout，在其中运行 `uv sync`，把 `keepygaga.example.toml` 复制为本机 `keepygaga.toml`，并把该运行环境原生的绝对路径记为其 `CONFIG_PATH`。为所有目标解析同一个物理记忆树：优先使用用户本轮明确提供的现有记忆树，其次复用现有 Keepygaga 配置中唯一且有效的记忆树；不要扫描整块磁盘。若没有现有记忆树，选择所有 Keepygaga checkout 之外、且不会公开共享或自动发布的可写新目录；只有访问范围私密且可信时才可使用同步目录。使用各运行环境的原生绝对路径，把每个配置的 `memory.root` 指向同一个物理记忆树。若候选不唯一、某个目标运行环境无法访问同一记忆树、路径映射无法核验或用户意图不清楚，先询问用户最小缺失项。不要在不同运行环境间复制或同步 `.venv`、`keepygaga.toml` 或记忆树。后续每条 Keepygaga CLI 命令都传入对应运行环境的 `--config CONFIG_PATH`。
3. 注册宿主前，在每个目标运行环境中运行 `uv run keepygaga --config CONFIG_PATH doctor --json`，检查各自 JSON 中 `id="memory_tree"` 的项目。检查为 `ok` 表示该运行环境看到的是有效记忆树；若 `warning` 的 `details.split_recommended` 为 `true`，记忆树同样有效且不阻止 setup。其他失败检查只有 `details.source_status` 为 `not_initialized` 时才允许 init。若出现其余失败状态、格式错误或具体页面无效，停止安装并报告确切运行环境和路径，不继续注册。共享记忆树是新目录或报告 `not_initialized` 时，只从一个目标运行环境运行一次 `uv run keepygaga --config CONFIG_PATH memory init`，创建或补齐规范结构，保存完整 JSON 供第 7 步使用，然后在每个目标运行环境中重新运行 Doctor，并以新的 `memory_tree` 检查为准。完成宿主 setup 和验证前不处理 `onboarding`。复用有效记忆树时，让每个配置直接指向它，不复制、不移动、不改写页面。`memory init` 是幂等命令：无需补齐文件时以 `no_op` 成功返回，并且绝不覆盖已有文件。
4. 目标为 Codex 时，运行 `uv run keepygaga --config CONFIG_PATH host setup codex`。该命令使用 Codex 自带 CLI 只对齐 `keepygaga` MCP 注册，并把带版本号的 `docs/agent-contract.md` 托管块安装到 Codex 实际生效的全局 `AGENTS.override.md` 或 `AGENTS.md` 入口；非空 override 优先，空 override 回退到 `AGENTS.md`，非生效候选已有托管块时因 stale/重复入口风险停止。不得手写这两项投影。若用户已经为本机选择并信任了兼容 Agent Hook Runtime，再追加 `--hook-runtime RUNTIME_ROOT --hook-python PYTHON`，命令会把 Hook 所有权和合并语义交给该 runtime；否则省略两个参数并报告可选 Hook 已跳过。目标不是 Codex 时，仍先检查 key `keepygaga` 下的 MCP 注册，再只注册或替换该项：使用目标环境虚拟环境的原生 Python，以 `-m keepygaga.server` 启动并传入绝对 `KEEPYGAGA_CONFIG=CONFIG_PATH`。
5. 仅对非 Codex 目标，把 `docs/agent-contract.md` 合并到宿主实际加载的全局规则入口并保留无关设置。Codex setup 只拥有 `KEEPYGAGA:START` 与 `KEEPYGAGA:END` 之间的精确托管块，只记录发行版本号而不使用内容哈希，并保持块外字节原位不变；不修改范围外 Agent 的全局规则。
6. 仅对支持 Hook 的非 Codex 目标，读取 `docs/hooks/README.md` 并选择对应专页，只安装该页支持的能力。Hook 使用与 Keepygaga 相同的物理记忆根，只合并 runtime 自有条目，保留无关宿主设置。没有兼容 runtime 时继续完成 MCP 安装并报告 Hook 未安装；不得自行编造或下载 Hook 可执行文件。
7. 在每个目标运行环境中重新运行 `uv run keepygaga --config CONFIG_PATH doctor --json` 和对应 checkout 中的 `uv run python scripts/smoke_mcp_server.py`。然后检查每个目标宿主实际显示的 MCP Tool 清单，确认各自都恰好暴露 list、read、create、add、update、move、rename、delete。若安装了 Hook，再完成各目标 Agent 专页中的验证。全部通过后才检查保存的 init JSON：只有 `status="applied"` 且 `onboarding.created_pages` 包含 `profile.md` 时，才 `read` 该页；若仍为空，提供一次可整体跳过的 Profile Onboarding。先说明 Profile 是共享该 Memory Root 的所有 Agent 都会加载的 Home Page——支持时直接注入，否则按 Agent Contract 主动读取。用户愿意继续时，一次询问最多四个可选项——希望的称呼、城市级常住地、职业和稳定长期角色，不询问精确地址。预览彼此独立的 `stated` Fact，核对 Profile Fact content 合计不超过 300 字符后通过 raw memory Tool 写入；跳过时不写任何标记。
8. 对 setup 前生效全局规则中没有完整 Keepygaga 托管块的每个目标，使用第 1 步保存的原文进行可选 Preference Extraction；已有托管块的目标视为重装、修复或升级并跳过。排除 Keepygaga 托管块、安全、权限、Skill、Hook、MCP、启动、Keepygaga 协议或工具路由规则、宿主专属与项目规则、当前状态、无依据推断和可从直接真源重取的事实。用户特有的条件检索偏好可以复制为证据，但凡原文被宿主当作检索或路由指令使用就绝不允许移动。对剩余共享软偏好跨目标去重，展示目标页预览，让用户选择跳过、复制并保留原文，或移动符合条件的条目；默认复制并保留。确认后先 `read preferences.md`，按 covered / refines / new / conflict 分类，并把候选作为 `stated` 写入。只有普通、宿主无关的回应或工作偏好且 Home Page 加载已验证时才提供移动；说明 Authority 降级并二次确认后，只删除托管块外精确匹配的原文，再复核标记、版本行和其他字节。无法验证资格或精确删除时只复制或保留。用户拒绝或无候选时不写，也不保存 onboarding 标记。

最终报告修改文件、memory root、各目标的 MCP 注册、验证结果和剩余缺口，绝不输出凭据。
```

## 使用

```bash
uv run keepygaga --config /absolute/path/to/keepygaga.toml doctor --json
uv run keepygaga --config /absolute/path/to/keepygaga.toml memory init
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup codex
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

更新 checkout，重新运行 `uv sync`，再执行同一条 setup 命令。对 Codex，
`host setup codex` 会按发行版本更新 Agent Contract 托管块、对齐 `keepygaga` MCP
transport，并刷新已选择的 Agent Hook Runtime 条目；完全一致时返回 `no_op`。非空
`AGENTS.override.md` 是生效规则入口，空 override 回退到 `AGENTS.md`；非生效候选
如果已有 Keepygaga 托管块，setup 会因 stale/重复入口风险停止。规则按原始 UTF-8
bytes 读取并保留块外字节；apply 顺序是 MCP、rules、可选 hooks，因此 MCP apply
失败时不会写入 rules。MCP 注册中的其他环境变量会保留；存在 CLI 无法无损保留的
自定义字段时 setup 会停止并要求人工决定。随后重启 Codex 并重新运行 Doctor 与
smoke test。其他宿主仍按各自当前合同检查和修复注册，并保留无关配置。

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
- 已应用的修改会返回服务端已经渲染的 receipt；请原样回显一次，绝不改写或杜撰读取、
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
