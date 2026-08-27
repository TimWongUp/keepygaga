# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**一个小而克制、local-first 的 Agent 长期记忆产品。**

Keepygaga 把少量真正耐久的用户事实保存在可读 Markdown 中，并独立提供完整运行时：八个 raw Tool 的 MCP Server、精简全局 Agent Contract、内置跨宿主 Hook，以及安装控制面。它不依赖数据库、向量索引、源码 checkout 或外部 Hook Runtime。

核心记忆由 `profile.md`、`preferences.md` 以及 `topics/`、`areas/`、`people/` 的直属页面组成。项目详情与当前状态仍以仓库或 live source 为准；Keepygaga 只保留项目位置和已完成重大里程碑。

公开 MCP Tool 固定为 `list`、`read`、`create`、`add`、`update`、`move`、`rename`、`delete`。

## 安装

要求 Python 3.12+ 和 [`uv`](https://docs.astral.sh/uv/)。

```shell
uv tool install keepygaga
keepygaga install
```

交互安装会检测可用宿主，但仍由用户选择。自动化安装必须显式列出全部目标：

```shell
keepygaga install --yes --host codex --host claude-code
```

当前适配 Codex、Claude Code、WorkBuddy、Grok、Hermes 与 Antigravity CLI。安装器只管理目标宿主的 `keepygaga` MCP 注册、Keepygaga 托管的 Agent Contract 块和 Hook 条目，保留其他配置。

默认配置与记忆目录使用各平台原生路径。首次安装如需复用已有私有记忆树，可传入 `--memory-root`；不要把记忆树放进公开或自动发布目录。

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
- 完整读取、收敛、mutation、冲突与 receipt 协议由 MCP `initialize.instructions` 下发。
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
