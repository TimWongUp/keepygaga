# GitHub Copilot CLI Hooks

GitHub Copilot CLI supports session and subagent context injection plus
write-triggered Closeout. `userPromptSubmitted` records the minimum pending
Closeout signal; it is not used as a visible memory-routing reminder.

- Live target: `~/.copilot/hooks/agent-hook-runtime.json`, under `hooks`.
- Required top-level field: `version: 1`; stop if an existing incompatible
  value is present.
- `sessionStart`: run `context_hook.py copilot sessionStart` with
  `timeoutSec: 10`.
- `subagentStart`: run `context_hook.py copilot subagentStart` with
  `timeoutSec: 10`. The current runtime injects the full versioned `profile.md`
  and `preferences.md`, a minimal canonical routing instruction, and the
  dynamic-page listing.
- `userPromptSubmitted`: run
  `closeout_hook.py copilot userPromptSubmitted` with `timeoutSec: 2`.
- `postToolUse` with matcher `create|edit|str_replace_editor|apply_patch`: run
  `closeout_hook.py copilot postToolUse` with `timeoutSec: 2`.

Copilot uses flat command objects and `timeoutSec`, not nested `hooks` wrappers.
Verify both start events and the two-stage Closeout flow. Do not claim a visible
per-turn routing reminder or compact Hook.
