# Qwen Code Hooks

Qwen Code supports session and subagent context injection, per-turn memory
routing, compact recovery, and write-triggered Closeout.

- Live target: `~/.qwen/settings.json`, under `hooks`.
- `SessionStart`: run `context_hook.py qwen SessionStart` with timeout `10000`
  milliseconds.
- `SubagentStart`: run `context_hook.py qwen SubagentStart` with timeout `10000`
  milliseconds. The current runtime injects the full versioned `profile.md` and
  `preferences.md`, a minimal canonical routing instruction, and the dynamic-page
  listing.
- `UserPromptSubmit`: run `memory_route_hook.py qwen UserPromptSubmit` with
  timeout `2000` milliseconds.
- `SessionStart` with matcher `compact`: run
  `memory_route_hook.py qwen SessionStart compact` with timeout `2000`
  milliseconds.
- `PostToolUse` with matcher `write_file|edit`: run
  `closeout_hook.py qwen PostToolUse` with timeout `2000` milliseconds.

Merge into nested `hooks` lists and preserve other matchers and commands. Verify
normal and compact session start, subagent start, one prompt, and one matching
write.
