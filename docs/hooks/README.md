# Built-in Hooks

Keepygaga owns Context Bootstrap and Memory Route. They are part of the published package and run through `keepygaga hook run context|route`; no external runtime or checkout is required.

Context Bootstrap reads the live Profile and Preferences pages and includes fixed scope-routing guidance. Memory Route is a stateless reminder for information routing and completion checks. Compact recovery restores the active task before checking for any omitted durable updates. Keepygaga does not register PostToolUse or Stop reminders, classify prompts by keywords, or maintain per-session Hook files.

`keepygaga install` projects only Keepygaga-owned commands into the selected host's native Hook configuration. Rerunning setup replaces current or legacy Keepygaga entries, including obsolete closeout commands, and preserves unrelated Hooks. `keepygaga uninstall` removes those owned entries only.

Codex and Claude Code use SessionStart, SubagentStart, UserPromptSubmit, and compact recovery. WorkBuddy uses SessionStart and UserPromptSubmit. Hermes and Antigravity CLI each combine bootstrap and routing in one native pre-invocation command. Grok relies on the managed Agent Contract because its passive lifecycle events do not provide this context-injection surface and blocking Stop feedback can replace the original final response.

See the host-specific notes for [Codex](codex.md), [Claude Code](claude-code.md), [WorkBuddy](workbuddy.md), [Hermes](hermes.md), [Antigravity CLI](antigravity.md), and [Grok](grok.md).
