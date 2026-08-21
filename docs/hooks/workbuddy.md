# WorkBuddy Hooks

WorkBuddy supports session context injection, per-turn memory routing, and
write-triggered Closeout. It does not install a separate subagent or compact
Hook through this contract.

- Live target: `~/.workbuddy/settings.json`, under `hooks`.
- `SessionStart`: run `context_hook.py workbuddy` with a 10-second timeout.
- `UserPromptSubmit`: run `memory_route_hook.py workbuddy UserPromptSubmit` with
  a 2-second timeout.
- `PostToolUse` with matcher `Write|Edit`: run
  `closeout_hook.py workbuddy PostToolUse` with a 2-second timeout.

Merge into each event's nested `hooks` list and preserve unrelated commands.
Verify one session start, one prompt, and one matching write; do not claim
subagent or compact support from the absence of an error.
