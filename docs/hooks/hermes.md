# Hermes Hooks

`keepygaga install --yes --host hermes` projects one Context Bootstrap command at `pre_llm_call` within `~/.hermes/config.yaml`. Hermes persists each turn's injected context in the conversation, so the first turn receives the live Profile and Preferences pages, scope-routing guidance, and the routing/completion reminder in one `context` payload, while later turns (`extra.is_first_turn` is `false`) receive only the reminder. A payload without that field receives the full bootstrap.

Hermes `subagent_start` is an observer event whose return value is ignored; it is not a context-injection surface. Keepygaga does not project a separate closeout event. Round-trip YAML merging removes obsolete Keepygaga-owned closeout and standalone route projections while preserving unrelated keys, comments, ordering, and Hook entries.
