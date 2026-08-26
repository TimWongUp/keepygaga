# Hook integration by Agent host

This directory is for the Agent installing Keepygaga. The installation scope
defaults to the current working Agent. Include another Agent only when the user
explicitly asks to install Keepygaga for it. For a single target, select exactly
one host page; for explicit multi-Agent installation, process each target
independently and select exactly one page per target. Do not modify non-target
Agents or infer one host's events or payload shape from another host.

| Agent host | Installation contract |
| --- | --- |
| Codex | [`codex.md`](codex.md) |
| Claude Code | [`claude-code.md`](claude-code.md) |
| WorkBuddy | [`workbuddy.md`](workbuddy.md) |
| Antigravity CLI | [`antigravity.md`](antigravity.md) |
| Gemini CLI | [`gemini-cli.md`](gemini-cli.md) |
| Qwen Code | [`qwen-code.md`](qwen-code.md) |
| GitHub Copilot CLI | [`github-copilot-cli.md`](github-copilot-cli.md) |
| Hermes | [`hermes.md`](hermes.md) |
| Grok | [`grok.md`](grok.md) |

当前支持的公开安装和卸载命令是 `keepygaga host setup|uninstall
codex|claude-code|workbuddy|grok|hermes|antigravity`。选定兼容 Agent Hook
Runtime 时传入其 runtime root 与 Python；每个适配器只读取 runtime 自己的同名
fragment 并调用其 `merge_hook_fragment`。卸载时用空 payload 只拆除 AHR-owned
条目，不改写 runtime `memory_root`，本目录不另存一份可执行 Hook payload。
`antigravity` 指 Antigravity CLI，不等同于 Gemini CLI；后者只有在真实 CLI 存在且
被单独适配后才能使用 `gemini-cli.md`。

## Shared preflight

Hooks are optional for the Keepygaga MCP server. A compatible runtime must
already provide these executable entrypoints:

```text
hooks/context_hook.py
hooks/memory_route_hook.py
hooks/closeout_hook.py
```

The currently tested runtime identifies itself as Agent Hook Runtime. Its source
location is deployment-specific and is not owned by Keepygaga. Do not invent,
download, or copy Hook executables merely because these instructions exist. If
no compatible runtime is available, finish the MCP installation and report that
Hook integration was not installed.

When Hook integration is installed, the target host must also load the current
Keepygaga Agent Contract and register the Keepygaga MCP server against the same
memory root. Do not install the memory Bootstrap, routing, or Closeout Hooks as
a standalone substitute for either prerequisite. Public `keepygaga host setup`
adapters coordinate all three; unsupported or manually composed hosts must
provide and verify both prerequisites before merging a Hook fragment.

Resolve the runtime's native absolute Python and checkout paths. Configure its
memory root to the same physical directory as Keepygaga `memory.root`, preferably
through `AGENT_HOOK_RUNTIME_MEMORY_ROOT`. Personal paths remain machine-local.

For each selected target, parse only that Agent's complete live host
configuration. Within the event keys documented by its selected host page,
replace only entries whose commands point to one of the three runtime
entrypoints, append the entries specified by that page, and preserve every
unrelated field and Hook. Do not inspect or rewrite a non-target Agent's
configuration, and never replace an entire configuration file or event key. Do
not install legacy safety or authorization Hooks.
