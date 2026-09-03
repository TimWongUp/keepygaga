# Hermes Hooks

`keepygaga install --yes --host hermes` projects Context Bootstrap and Memory Route at `pre_llm_call` within `~/.hermes/config.yaml`. Hermes `pre_verify` is an edited-code verification gate rather than a general closeout context hook, so Keepygaga does not project Memory Closeout there. Round-trip YAML merging removes obsolete Keepygaga-owned projections while preserving unrelated keys, comments, ordering, and Hook entries.
