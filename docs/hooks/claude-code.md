# Claude Code Hooks

Claude Code supports session and subagent context injection, per-turn memory
routing, compact recovery, and write-triggered Closeout.

- Live target: `~/.claude/settings.json`, under `hooks`; when CC Switch manages
  the active provider, update that provider's current settings through the same
  merge contract.
- `SessionStart`: run `context_hook.py claude` with a 10-second timeout.
- `SubagentStart`: run `context_hook.py claude` with a 10-second timeout. The
  current runtime injects the full versioned `profile.md` and `preferences.md`,
  a minimal canonical routing instruction, and the dynamic-page listing.
- `UserPromptSubmit`: run `memory_route_hook.py claude UserPromptSubmit` with a
  2-second timeout.
- `SessionStart` with matcher `compact`: run
  `memory_route_hook.py claude SessionStart compact` with a 2-second timeout.
- `PostToolUse` with matcher `Write|Edit`: run
  `closeout_hook.py claude PostToolUse` with a 2-second timeout.

Claude wraps commands inside each event's `hooks` list. Preserve other matchers
and commands. Verify normal and compact session start, subagent start, one user
prompt, and one matching write; confirm Closeout does not repeat for unchanged
pending state.
