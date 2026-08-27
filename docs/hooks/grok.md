# Grok Hooks

`keepygaga install --yes --host grok` manages `~/.grok/hooks/keepygaga.json`. Grok currently exposes a Stop projection, used for Memory Closeout when the turn ends normally. Re-entry signals prevent an infinite stop-hook loop.

Setup migrates ownership away from legacy Keepygaga command markers without changing unrelated Hook entries. MCP live verification still uses Grok's official MCP list and doctor commands.
