# Use bounded scoped routing without Store matching

**Status:** accepted

Keepygaga will stop injecting the dynamic Route Catalog at startup, define `topics`, `areas`, and `people` as independently bounded Memory Scopes, and require `list` to return one complete scope at a time. The Store will not add search, matching, pagination, or semantic placement; the Agent selects and reads candidate pages, then organizes dynamic pages through deterministic versioned mutations. This trades unrestricted catalog growth for a small predictable protocol whose worst-case routing payload is controlled by per-scope page admission.
