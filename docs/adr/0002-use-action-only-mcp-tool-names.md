# Use action-only MCP Tool names

Status: accepted; the client registration key is superseded by ADR-0003.

Keepygaga documents `gaga` as the MCP client registration key and exposes raw Tools `list`, `read`, `create`, `add`, `update`, `move`, `rename` and `delete`. The client key is separate from FastMCP `serverInfo.name`; hosts that use the documented key produce concise canonical names such as `mcp__gaga__read` without repeating product and resource prefixes.
