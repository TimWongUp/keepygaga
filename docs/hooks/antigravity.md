# Antigravity CLI Hooks

Antigravity CLI supports context injection and memory routing at
`PreInvocation`. Its `AfterTool` output is not consumed as a model reminder, so
Closeout is intentionally not registered; final Closeout remains a global-rule
responsibility.

- Live target: `~/.gemini/config/hooks.json`, under
  `shared-context-bootstrap`.
- `PreInvocation`: run `context_hook.py agy_cli PreInvocation` with a 10-second
  timeout.
- The same `PreInvocation`: run
  `memory_route_hook.py agy_cli PreInvocation` with a 2-second timeout.

The target node is a named Hook group, not a generic `hooks` object. Preserve
other groups and entries. Verify that both commands' output reaches model
context before an invocation; do not install `AfterTool` or `Stop` Closeout.
