# Codex Hooks

`keepygaga install --yes --host codex` projects built-in commands into the effective Codex Hook configuration. SessionStart loads core bootstrap context, UserPromptSubmit injects the routing reminder, PostToolUse performs deduplicated closeout, and SubagentStart receives a lightweight routing instruction.

The adapter preserves unrelated Hook entries, uses the installed `keepygaga` launcher and absolute config path, and fails closed on invalid JSON or concurrent changes. Repeated setup is a no-op; uninstall removes current and legacy Keepygaga-owned entries only.
