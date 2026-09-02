# Automate low-risk preference observations without candidate tracking

**Status:** superseded by ADR 0005

Keepygaga allows an Agent to write low-sensitivity Preference Facts as `observed` without per-Fact confirmation when the current visible context already contains repeated direct evidence, and requires Agent-side Fact Convergence against the live page before mutation. It deliberately does not add a candidate pool, history scan, evidence counter, provenance record, background model, or Store-level semantic matcher, so isolated observations cannot accumulate across sessions; new Profile Facts remain `stated` only, and Home Page Preferences use a soft-limit growth gate instead of an automatic overflow mechanism.
