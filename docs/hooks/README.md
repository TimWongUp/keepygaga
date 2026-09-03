# Built-in Hooks

Keepygaga owns three semantic Hooks: Context Bootstrap, Memory Route, and Memory Closeout. They are part of the published package and run through the stable `keepygaga hook run` command; no external runtime or checkout is required.

`keepygaga install` projects only Keepygaga-owned commands into the selected host's native Hook configuration. Rerunning setup replaces current or legacy Keepygaga entries and preserves unrelated Hooks. `keepygaga uninstall` removes those owned entries only.

Host capability varies. Codex, Claude Code, and WorkBuddy can receive all three capabilities; Hermes maps them to its native lifecycle; Antigravity currently receives bootstrap and route. Grok uses the managed Agent Contract as its closeout fallback because its blocking `Stop` feedback starts another inference round and can replace the original final response in headless clients. Omitted capabilities are unsupported projections, not silent failures.

See [Codex](codex.md) and [Grok](grok.md) for host-specific notes. Other supported host paths are maintained by their adapter and covered by configuration tests.
