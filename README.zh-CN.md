# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**给所有编码 Agent 一套少而准的共享核心记忆。**

AI 不是记得越多越好。把每次对话、临时状态和项目细节都塞进长期记忆，只会让真正有用的信息被过时、无关的内容淹没。没有选择的记忆不是上下文，而是噪声。

Keepygaga 只保存少量、能跨任务长期发挥作用的信息：用户是谁、希望 Agent 怎样工作，以及少数持续关注的主题、项目、责任或人物关系。临时状态留在当前对话或它的直接真源里，例如日历、任务管理器、项目文档、Issue 或 Git 历史。只有经过明确判断、确认能跨任务长期发挥作用的事实，才进入核心记忆。

这套经过筛选的核心记忆属于用户，并随用户在 Codex、Claude Code、WorkBuddy、Grok、Hermes 与 Antigravity CLI 之间流动，而不是被困在各宿主的记忆孤岛中。唯一事实源是一个私有 Memory Root 中的可读 Markdown；推荐把它放进 Obsidian Vault，也兼容任意 Markdown 编辑器。

产品刻意分成三个界面：

- **Obsidian 或其他 Markdown 编辑器**供人查看、纠正和整理记忆。
- **MCP、Hook 与 Agent Contract**让 Agent 在明确约束下读取和修改记忆。
- **`keepygaga` CLI**是薄的安装与运维控制面，只负责宿主接线、状态、诊断、修复、升级和卸载，不承担日常记忆浏览或编辑。

Keepygaga 独立提供完整运行时：八个 raw Tool 的 MCP Server、精简全局 Agent Contract、内置跨宿主 Hook，以及 CLI 控制面。它不依赖数据库、向量索引、源码 checkout 或外部 Hook Runtime；Obsidian 是推荐的人类界面，不是运行依赖。

核心记忆由 `profile.md`、`preferences.md` 以及 `topics/`、`areas/`、`people/` 的直属页面组成。对代码项目来说，Keepygaga 不替代仓库自己的术语、架构、操作说明、重要决定与当前状态，只保留项目位置和已完成重大里程碑。

宿主原生记忆可以继续负责该宿主的会话召回与项目内学习；Keepygaga 只负责应当随用户跨宿主流动的少量稳定事实。

公开 MCP Tool 固定为 `list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`。

### 升级到 0.5

0.5 将每个 `move` operation 的单个 `fact` 字段改为必填的 `facts` 数组。升级后，缓存过 MCP schema 的客户端需要重新连接或刷新 Tool schema，并把同一源页/目标页的全部精确 Fact 放进该数组。这只改变 MCP 请求结构，不改变 Markdown 记忆格式，也不需要迁移现有记忆文件。

## 安装

要求 Python 3.12+ 和 [`uv`](https://docs.astral.sh/uv/)。

```shell
uv tool install keepygaga
keepygaga install
```

交互安装会先让用户确认或输入 Memory Root，再检测可用宿主并由用户选择。已有 `agents-memory` 记忆树可以直接接入；配置完成后，后续新增 Agent 会自动复用该目录。自动化安装必须显式列出全部目标：

```shell
keepygaga install --yes --host codex --host claude-code
```

当前适配 Codex、Claude Code、WorkBuddy、Grok、Hermes 与 Antigravity CLI。安装器只管理目标宿主的 `keepygaga` MCP 注册、Keepygaga 托管的 Agent Contract 块和 Hook 条目，保留其他配置。

默认配置与记忆目录使用各平台原生路径。非交互首次安装如需复用已有私有记忆树，可传入 `--memory-root`；不要把记忆树放进公开或自动发布目录。

## 运维

```shell
keepygaga status
keepygaga repair --yes
keepygaga upgrade --yes
keepygaga doctor --json
keepygaga uninstall --yes
```

`status` 只把安装状态文件当作发现线索，并明确标识仍需真实宿主验证的部分。`repair` 依据 live 配置重新对齐已记录宿主；`upgrade` 通过 `uv` 更新到最新已发布版本，再自动修复宿主接线；`uninstall` 只拆除 Keepygaga 接线，保留配置与记忆树。

高级确定性入口仍为 `keepygaga host setup|uninstall HOST`。

## 集成结构

- 宿主 MCP 注册统一指向稳定启动器 `keepygaga-mcp`。
- 精简 Agent Contract 只保留稳定安全与路由规则。
- 完整读取、收敛、mutation、冲突与 receipt 协议由协商后的 MCP Server instructions 下发（现代 discovery 或旧式 initialize 握手）。
- 内置 Context Bootstrap、Memory Route、Memory Closeout 三个语义 Hook，再投影为各宿主的原生事件格式。
- 应用、Agent Contract、Hook 协议、安装状态和记忆 schema 分别演进版本。

配置级测试只证明投影、保留、幂等与失败边界；只有真实客户端或官方诊断确认 `keepygaga` 注册和八个 Tool 后，才能称为现场验证。

## 开发验证

```shell
uv sync
uv run pytest -q
uv run ruff check .
uv run pyright
uv run python scripts/smoke_mcp_server.py
uv build
uv run python scripts/check_distribution.py dist/*
```

Sibling 项目 `keepygaga-knowledge` 与本项目完全独立，不进入 Keepygaga 包，也不被运行时 import。参见 [架构](docs/architecture.md)、[运维](docs/operations.md) 与 [贡献指南](CONTRIBUTING.md)。

## 安全与许可证

记忆文件是可信本地输入，可能含个人信息。请保持 Memory Root 私密，并在提交到任何仓库前检查内容。安全问题请使用 [GitHub 私密漏洞报告](https://github.com/TimWongUp/keepygaga/security/advisories/new)。

MIT License，见 [LICENSE](LICENSE)。
