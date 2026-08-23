# Codex Hooks

Codex Hook 只通过幂等宿主 setup 投影：

```bash
uv run keepygaga --config CONFIG_PATH host setup codex \
  --hook-runtime RUNTIME_ROOT \
  --hook-python PYTHON
```

`RUNTIME_ROOT` 必须是用户已经选择并信任的兼容 Agent Hook Runtime checkout，`PYTHON`
必须能直接运行该 runtime。setup 读取 runtime 自己的
`config/hooks/codex.json`，使用它提供的 `merge_hook_fragment`，并把 runtime config
的 `memory_root` 对齐 Keepygaga 配置；Keepygaga 不复制或推断事件、matcher、timeout
和 command payload。

setup 会在写入 Codex 配置前完成 runtime、fragment、合并器、命令路径和环境预检。
`AGENT_HOOK_RUNTIME_MEMORY_ROOT` 若已设置，必须与 Keepygaga 的 `memory.root`
一致。若显式传入 `--hook-config`，该绝对路径必须与 Agent Hook Runtime 实际加载的
路径一致；通常应省略此参数并使用 runtime 默认配置，测试或自定义位置则同时设置
同值的 `AGENT_HOOK_RUNTIME_CONFIG`。符号链接配置路径和可能触发 shell 展开的命令
路径会被拒绝。

投影目标是 Codex home 下的 `hooks.json#/hooks`。完成条件：runtime 的 context
smoke 成功，AHR-owned 条目与 fragment 一致，其他 Codex Hook 和顶层字段保持不变。
没有兼容 runtime 时省略两个 Hook 参数；MCP 与全局 Agent Contract 仍完成安装，
结果明确返回 `hooks.status="skipped"`。
