# Keep Fact evidence metadata minimal

**Status:** accepted; supersedes ADR 0002

Fact evidence remains exactly `stated|observed`: `stated` is the user's explicit statement, while `observed` covers Agent derivation or inference from current visible material on any admissible page. Keepygaga will not add provenance, confidence, inference reasons, source references, evidence counters, or time-validity fields; it adds only an optional Store-owned local date for the Fact's last actual addition or update. The deliberately minimal tail syntax reserves terminal ` [YYYY-MM-DD]` for that date; legacy undated Facts otherwise remain valid without migration. This makes inference visible without turning core memory into an evidence ledger, while current user statements continue to override conflicting observations.
