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

普通验证不修改真实 Vault；测试使用临时 memory tree。当前配置与 live 页面状态必须从 `keepygaga.toml`、Doctor 和目标 Markdown 现场刷新，不能从本文推断。

## Doctor semantics

- `ok`：所有适用核心记忆检查正常。
- `warning`：存在需要关注但未阻断的检查；读取具体 check 后再下结论。
- `error`：配置、目录、格式、身份冲突或可写性等直接检查失败。

Doctor 只报告非敏感 metadata，不输出正文、凭据、API key、cookie 或 session。公开协议可用性由 MCP smoke 独立验证。

## Failure routing

- 配置加载失败：核对 config path 与 `[memory].root`，示例值不代表本机状态。
- 页面格式无效：停止 mutation，报告 exact path 和错误，保留原文。
- version 冲突：重新 `read` latest，明确合并后重试。
- name 或 alias identity 冲突：修正目标页面或输入，不绕过全库验证。
- `write_failed`：首个文件尚未提交时写入失败；现场未应用本批次内容，排除文件系统问题后重新读取并重试。
- `partial_commit`：响应中的 `applied_paths` 已完成替换，其余路径未完成；重新读取整批相关页面并明确合并，不重复提交原批次，也不假设跨文件回滚。
- smoke 失败：先核对 raw Tool 集合与 schema，再进入对应 Store 实现；不以 Doctor 替代协议验证。
- wheel smoke 失败：先区分发行包内容、console script 生成和 MCP 协议失败；源码 smoke
  通过不能替代已安装 artifact 的验证。

## Evidence

测试输出、smoke、Doctor 和原始错误属于 Evidence；分支、进程、端口和一次性实验属于 Run。稳定语义变化更新 `CONTEXT.md`、本目录或 ADR，当前状态不写成长期结论。
