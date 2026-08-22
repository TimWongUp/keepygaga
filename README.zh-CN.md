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

1. 根据用户请求确定 `TARGET_HOSTS`：默认只包含当前工作的 Agent，只有用户明确要求为某个其他 Agent 安装 Keepygaga 时才将其加入。读取仓库 `AGENTS.md` 和每个目标宿主的 MCP 文档，确认各目标实际运行在原生 Windows、macOS、Linux 还是 WSL，并按运行环境归组为 `TARGET_RUNTIMES`。逐个处理目标，不修改范围外的 Agent。
2. 对每个不同的目标运行环境，使用该环境可访问的 Keepygaga checkout，在其中运行 `uv sync`，把 `keepygaga.example.toml` 复制为本机 `keepygaga.toml`，并把该运行环境原生的绝对路径记为其 `CONFIG_PATH`。为所有目标解析同一个物理记忆树：优先使用用户本轮明确提供的现有记忆树，其次复用现有 Keepygaga 配置中唯一且有效的记忆树；不要扫描整块磁盘。若没有现有记忆树，选择所有 Keepygaga checkout 之外、且不会公开共享或自动发布的可写新目录；只有访问范围私密且可信时才可使用同步目录。使用各运行环境的原生绝对路径，把每个配置的 `memory.root` 指向同一个物理记忆树。若候选不唯一、某个目标运行环境无法访问同一记忆树、路径映射无法核验或用户意图不清楚，先询问用户最小缺失项。不要在不同运行环境间复制或同步 `.venv`、`keepygaga.toml` 或记忆树。后续每条 Keepygaga CLI 命令都传入对应运行环境的 `--config CONFIG_PATH`。
3. 注册宿主前，在每个目标运行环境中运行 `uv run keepygaga --config CONFIG_PATH doctor --json`，检查各自 JSON 中 `id="memory_tree"` 的项目。检查为 `ok` 表示该运行环境看到的是有效记忆树；失败检查的 `details.source_status` 为 `not_initialized` 时才允许 init。若出现其他失败状态、格式错误或具体页面无效，停止安装并报告确切运行环境和路径，不继续注册。共享记忆树是新目录或报告 `not_initialized` 时，只从一个目标运行环境运行一次 `uv run keepygaga --config CONFIG_PATH memory init`，创建或补齐规范结构，然后在每个目标运行环境中重新运行 Doctor，并以新的 `memory_tree` 检查为准。复用有效记忆树时，让每个配置直接指向它，不复制、不移动、不改写页面。`memory init` 是幂等命令：无需补齐文件时以 `no_op` 成功返回，并且绝不覆盖已有文件。
4. 对每个目标宿主，先检查 key `keepygaga` 下是否已有 MCP 注册，再只注册或替换这一项：使用该目标运行环境中仓库虚拟环境的原生 Python，以 `-m` 和 `keepygaga.server` 作为参数，把 `keepygaga.server` 注册为 stdio server，并把绝对 `KEEPYGAGA_CONFIG` 设为该运行环境的 `CONFIG_PATH`。删除不属于当前注册的过时 Keepygaga 启动参数或环境字段，确认可执行文件和模块存在，保留宿主全部无关 MCP 设置，不修改范围外 Agent 的注册。
5. 对每个目标宿主，把 `docs/agent-contract.md` 合并到该宿主实际加载的全局规则入口，保留无关设置；不修改范围外 Agent 的全局规则。
6. 对每个支持 Hook 的目标宿主，读取 `docs/hooks/README.md`，只选择该宿主对应的专页，并且只安装该页明确支持的能力。Hook 必须使用与 Keepygaga 相同的物理记忆根，只合并该 runtime 自有条目，保留宿主全部无关设置，不修改范围外 Agent 的 Hook。若某个目标没有兼容 runtime，继续完成其 MCP 安装并明确报告 Hook 未安装；不得自行编造或下载 Hook 可执行文件。
7. 在每个目标运行环境中重新运行 `uv run keepygaga --config CONFIG_PATH doctor --json` 和对应 checkout 中的 `uv run python scripts/smoke_mcp_server.py`。然后检查每个目标宿主实际显示的 MCP Tool 清单，确认各自都恰好暴露 list、read、create、add、update、move、rename、delete。若安装了 Hook，再完成各目标 Agent 专页中的验证。
8. 仅在首次安装时，检查本次安装前已存在于各目标宿主实际加载的全局规则中的内容，筛出“用户希望 Agent 如何回应和工作”的长期个人偏好候选；重装、修复或升级时跳过，也不把本次合并的 Agent Contract 或安装指令作为候选来源。排除安全边界、工具或记忆路由、项目规则、当前状态、推断和可从直接真源重取的事实。跨目标去重后向用户展示候选，并只问一次是否导入 `preferences.md`；明确确认前不写。确认后先 `read` `preferences.md`，按 covered / refines / new / conflict 处理，并把用户确认的候选以 `stated` 写入；拒绝或无候选则不写，也不保存 onboarding 标记。

最终报告修改文件、memory root、各目标的 MCP 注册、验证结果和剩余缺口，绝不输出凭据。
```

## 使用

```bash
uv run keepygaga --config /absolute/path/to/keepygaga.toml doctor --json
uv run keepygaga --config /absolute/path/to/keepygaga.toml memory init
```

`doctor` 只检查核心记忆并报告八个 raw Tool。`memory init` 创建规范
Markdown 记忆树；记忆树已完整时以 `no_op` 成功返回，且拒绝覆盖已有文件。
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

重启宿主前先检查现有 `keepygaga` 条目，把旧脚本路径或参数替换为当前虚拟环境
Python 加 `-m keepygaga.server`，删除过时的 Keepygaga 自有字段，保留所有无关
MCP 条目，并重新运行 Doctor 与 smoke test。

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
- 容量限制为软限制：写入仍会成功，并返回 `split_recommended`。
- Keepygaga 永远不会自行删除、压缩或移动已有记忆。
- 删除操作必须获得用户在当前轮次中的明确授权。
- 已应用的修改会返回服务端生成的 receipt；请原样回显一次，绝不杜撰读取、
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
