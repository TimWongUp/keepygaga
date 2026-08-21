# Codex Hooks

Codex supports session and subagent context injection, per-turn memory routing,
compact recovery, and write-triggered Closeout. `SessionStart` does not carry
its injected context into internal subagents, so `SubagentStart` independently
loads the same full core-memory bootstrap.

- Live target: `~/.codex/hooks.json`, under `hooks`.
- `SessionStart`: run `context_hook.py codex` with a 10-second timeout and
  `additionalContextLimit: 0`.
- `SubagentStart`: run `context_hook.py codex SubagentStart` with a 10-second
  timeout and `additionalContextLimit: 0`.
- `UserPromptSubmit`: run `memory_route_hook.py codex UserPromptSubmit` with a
  2-second timeout and `additionalContextLimit: 120`.
- `SessionStart` with matcher `^compact$`: run
  `memory_route_hook.py codex SessionStart compact` with a 2-second timeout and
  `additionalContextLimit: 180`.
- `PostToolUse` with matcher `Write|Edit`: run
  `closeout_hook.py codex PostToolUse` with a 2-second timeout.

Use absolute, independently quoted Python and runtime paths. Merge only these
entries into the live `hooks` object. Verify `SessionStart`, `SubagentStart`, one
user prompt, compact recovery, and one matching file write; confirm Closeout is
emitted at most once for the same pending state.
