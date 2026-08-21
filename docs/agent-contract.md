# Keepygaga Agent Contract

- Current user instructions and project Authority override memory.
- Apply relevant `preferences.md` facts by default. For other context, call `list`, select pages by description or aliases, and pass listed paths unchanged to `read`.
- Write only stable personal context that will materially improve future sessions. Keep transient task state, reproducible source data, advice, inference, and secrets out of core memory.
- Keep three-month identity and background in `profile.md`. Stable project affiliation or a long-term project role may be Profile context when it improves cross-task interaction; keep project implementation, decisions, plans, progress, and runtime state in project Authority or one direct `areas/` page.
- Keep response and working preferences in `preferences.md`; route other personal facts to one direct `topics/`, `areas/`, or `people/` page.
- Treat each Fact as one independently maintainable assertion. Classify incoming information as covered, refines, new, or conflict: skip covered, `update` refinements, `add` independent facts, and resolve conflicts against the user's current statement or direct evidence.
- Read before modifying an existing page and use its current version. On conflict, read latest and merge intentionally.
- Use Keepygaga mutation Tools for core memory. Delete only with explicit user authorization in the current turn.
- Echo each applied mutation receipt exactly once. Receipts already include safe CommonMark inline-code markup; show no receipt for reads, no-ops, skips, or failures.
