# Use keepygaga as the MCP host ID

Keepygaga uses `keepygaga` as its MCP client registration key, producing host names such as `mcp__keepygaga__read`. This supersedes the shorter `gaga` key from ADR-0002: keeping the product name visible in cross-agent tool traces is worth the added length, while FastMCP `serverInfo.name` and the action-only raw Tool names remain unchanged.
