# Codex Hooks

`keepygaga install --yes --host codex` projects built-in commands into the effective Codex Hook configuration. SessionStart and SubagentStart load the same core bootstrap context from the live Profile and Preferences pages, including scope-routing guidance. UserPromptSubmit reminds the Agent to route information and check durable context before completion. SessionStart with source `compact` additionally injects recovery guidance.

The adapter removes obsolete Keepygaga PostToolUse closeout commands while preserving unrelated Hook entries. Commands use the installed `keepygaga` launcher and absolute config path. Invalid JSON or concurrent changes fail closed. Repeated setup is a no-op; uninstall removes current and legacy Keepygaga-owned entries only.
