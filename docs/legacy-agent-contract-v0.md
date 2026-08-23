# Keepygaga Agent Contract

- Current user instructions and project Authority override memory.
- Apply relevant `preferences.md` facts by default. For other context, call `list`, select pages by description or aliases, and pass listed paths unchanged to `read`.
- Write only durable cross-session context that will materially improve future sessions. Keep transient task state, reproducible source data, advice, inference, and secrets out of core memory.
- Keep three-month identity and background in `profile.md`. Stable project affiliation or a long-term project role may be Profile context when it improves cross-task interaction.
- Maintain a minimal project index in one direct `areas/` page: each ongoing project's storage location and a brief record of completed major milestones. Keep project details, decisions, plans, and current state in project Authority or direct sources; they override the index when they differ.
- Read the project index to locate known projects and recall major progress, then consult project Authority or direct sources before asserting details. Update only when a project is first recorded or moved, or when a milestone changes the overall understanding of the project; do not mirror roles, stage snapshots, plans, blockers, next steps, commits, task logs, test runs, or transient runtime state.
- Keep response and working preferences in `preferences.md`; route other personal facts to one direct `topics/`, `areas/`, or `people/` page.
- Treat each Fact as one independently maintainable assertion. Classify incoming information as covered, refines, new, or conflict: skip covered, `update` refinements, `add` independent facts, and resolve conflicts against the user's current statement or direct evidence.
- Read before modifying an existing page and use its current version. On conflict, read latest and merge intentionally.
- Use Keepygaga mutation Tools for core memory. Delete only with explicit user authorization in the current turn.
- Echo each applied mutation receipt exactly once. Receipts already include safe CommonMark inline-code markup; show no receipt for reads, no-ops, skips, or failures.
