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
