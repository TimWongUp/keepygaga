# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**AI Agent 的记忆守护者。**

Keepygaga 是一个温和、local-first 的记忆守护工具。持久的用户与环境记忆以
可读的 Markdown 保存，每一次修改都由显式、带版本控制的 MCP 工具完成。没有
数据库、索引或 Embedding 服务：记忆树本身就是产品。

它刻意保持精简的 MCP 接口——恰好八个动作型工具：

- `list` 和 `read` 用于发现和读取规范记忆页面。
- `create` 和 `add` 用于创建页面和新增事实。
- `update` 用于演化精确事实或页面元数据（由 `target` 判别）。
- `move` 和 `rename` 用于移动事实和重命名页面。
- `delete` 删除精确事实或页面，始终要求显式
  `authorization="user_requested"`。

核心记忆由 `profile.md`、`preferences.md`，以及 `topics/`、`areas/` 和
`people/` 下的直属页面组成。核心记忆永不进入索引。项目指令仍保留在各项目
自己的 Agent 入口和长期上下文中。

## 环境要求

- Python 3.12+
- 一个用于存放 `agents-memory` 记忆树的可写本地目录
- 推荐使用 [`uv`](https://docs.astral.sh/uv/)

Obsidian 是可选的，仅推荐用于方便地浏览和手工编辑 Markdown 记忆；
Keepygaga 可以直接使用普通文件系统目录，不要求安装或运行 Obsidian。

## 安装

把下面的 prompt 发给需要接入 Keepygaga 的目标 Agent：

```text
请为你自己安装并接入 https://github.com/TimWongUp/keepygaga。

1. 读取仓库 `AGENTS.md` 和当前宿主的 MCP 文档，并确认 Agent 实际运行在原生 Windows、macOS、Linux 还是 WSL；后续路径和 Python 可执行文件必须属于同一运行环境。
2. 运行 `uv sync`，把 `keepygaga.example.toml` 复制为本机 `keepygaga.toml`，再解析 `memory.root`：优先使用用户本轮明确提供的现有记忆树，其次复用现有 Keepygaga 配置中唯一且有效的记忆树；不要扫描整块磁盘。若没有现有记忆树，选择一个可写的新目录；若候选不唯一或意图不清楚，先询问用户最小缺失项。
3. 如果复用现有记忆树，把 `memory.root` 直接指向它，不复制、不移动、不改写页面，并先运行 `uv run keepygaga doctor --json`。读取 JSON 中 `id="memory_tree"` 的检查：仅当其 message 明确报告未初始化时，才运行 `uv run keepygaga memory init` 补齐缺失结构；如果报告 `invalid_source`、格式错误或具体页面无效，停止安装并把确切路径报告给用户，不运行 init，也不继续注册。init 后无论命令退出码或 payload 是 `applied` 还是 `no_op`，都重新运行 Doctor，并以新的 `memory_tree` 检查为准。如果使用新目录，运行 init 创建规范树。`memory init` 不得覆盖已有文件。
4. 使用仓库虚拟环境中的原生 Python 和绝对 `KEEPYGAGA_CONFIG`，把 `mcp_server.py` 作为 stdio server 注册到 key `keepygaga`；保留宿主其他 MCP 配置，不同步 `.venv` 或 `keepygaga.toml` 到其他机器。
5. 把 `docs/agent-contract.md` 合并到宿主实际加载的全局规则入口，保留无关设置。
6. 运行 `uv run keepygaga doctor --json` 和 `uv run python scripts/smoke_mcp_server.py`，再确认宿主恰好暴露 list、read、create、add、update、move、rename、delete。
7. 仅在首次安装时，检查本次安装前已存在于宿主实际加载的全局规则中的内容，筛出“用户希望 Agent 如何回应和工作”的长期个人偏好候选；重装、修复或升级时跳过，也不把本次合并的 Agent Contract 或安装指令作为候选来源。排除安全边界、工具或记忆路由、项目规则、当前状态、推断和可从直接真源重取的事实。向用户展示去重后的候选，并只问一次是否导入 `preferences.md`；明确确认前不写。确认后先 `read` `preferences.md`，按 covered / refines / new / conflict 处理，并把用户确认的候选以 `stated` 写入；拒绝或无候选则不写，也不保存 onboarding 标记。

最终报告修改文件、memory root、MCP 注册、验证结果和剩余缺口，绝不输出凭据。
```

## 使用

```bash
uv run keepygaga doctor
uv run keepygaga memory init
uv run python mcp_server.py
```

`doctor` 只检查核心记忆并报告八个 raw Tool。`memory init` 创建规范
Markdown 记忆树，且拒绝覆盖已有文件。不带子命令运行 CLI 时显示帮助。

在 MCP 宿主中以 ID `keepygaga` 注册本服务，完整宿主工具名形如
`mcp__keepygaga__read`：

```json
{
  "mcpServers": {
    "keepygaga": {
      "command": "/path/to/keepygaga/venv/bin/python",
      "args": ["/path/to/keepygaga/mcp_server.py"],
      "env": {
        "KEEPYGAGA_CONFIG": "/path/to/keepygaga.toml"
      }
    }
  }
}
```

`KEEPYGAGA_CONFIG` 用于覆盖默认配置路径。

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

## 致谢

Keepygaga 的核心记忆设计受到 Claude 记忆系统的启发。

也感谢 Claude 团队在 AI 记忆领域的开创性工作。

## 许可证

[MIT](LICENSE)
