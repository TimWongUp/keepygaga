# Antigravity CLI Hooks

`keepygaga install --yes --host antigravity` projects two commands into `~/.gemini/config/hooks.json` under `shared-context-bootstrap`. `SessionStart` injects the live Profile, Preferences, and scope-routing guidance once as a persistent `systemMessage`; `PreInvocation` injects only the short routing/completion reminder as an `ephemeralMessage`. Setup replaces the older full-bootstrap `PreInvocation` command while preserving unrelated Hooks.

Antigravity CLI is not Gemini CLI. Keepygaga does not project PostToolUse or Stop reminders.
