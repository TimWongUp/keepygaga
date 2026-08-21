# Split core memory and knowledge retrieval into separate repositories

Keepygaga owns the open-source core-memory contract, while the less mature Knowledge/RAG subsystem lives in the independent `keepygaga-knowledge` repository. The two products have different release readiness, dependencies and operational lifecycles, so they integrate through separate MCP Server registrations instead of a shared Python package or repository.
