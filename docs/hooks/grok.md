# Grok Hooks

Grok uses the managed Agent Contract for memory routing and completion checks. Keepygaga does not register a Grok `Stop` Hook because model-visible Stop feedback necessarily starts another inference round and can replace the original final response in headless clients.

Setup and repair remove obsolete Keepygaga-owned Grok Hook commands without changing unrelated Hook entries. After updating Grok through the Agent fast path, run `keepygaga install --yes --host grok` so this removal is applied only to Grok. Use `keepygaga repair --yes` only when the user explicitly intends to reconcile every recorded host. MCP live verification still uses Grok's official MCP list and doctor commands.
