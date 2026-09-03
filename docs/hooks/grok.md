# Grok Hooks

Grok uses the managed Agent Contract for Memory Closeout. Keepygaga does not register a Grok `Stop` Hook because model-visible Stop feedback necessarily starts another inference round and can replace the original final response in headless clients.

Setup and repair remove obsolete Keepygaga-owned Grok Hook commands without changing unrelated Hook entries. After reinstalling a newer GitHub Release wheel, run `keepygaga repair --yes` so this removal is applied to existing installations. MCP live verification still uses Grok's official MCP list and doctor commands.
