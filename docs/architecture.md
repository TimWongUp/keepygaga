# Keepygaga Architecture

## Product boundary

Keepygaga is a user-owned cross-host core-memory layer: one Memory Root is shared by every configured Agent host. The recommended human interface is a private Obsidian vault, while any Markdown editor remains compatible. Obsidian is not a runtime dependency.

Keepygaga is one independently installable Python product. The published wheel owns the MCP server, stable launchers, memory store, Agent Contract, built-in Hooks, host adapters, installation and operations control plane, and diagnostics. The `keepygaga` CLI performs installation, host wiring, status, diagnosis, repair, upgrades, and uninstall; it is not a daily memory browser or editor. It neither imports nor packages `keepygaga-knowledge`, `agent-runtime-config`, or an external Agent Hook Runtime.

The sibling `keepygaga-knowledge` repository may consume the same Markdown ecosystem, but it is not a runtime dependency and exposes no tool through this server.

Host-native memory remains free to own host-specific conversation recall and project learning. Keepygaga owns only the stable user facts that should cross host boundaries; project authority remains in project-owned sources.

## Runtime layers

1. `MemoryStore` owns canonical Markdown parsing, validation, versioned mutations, locking, and atomic replacement.
2. `server.py` publishes exactly eight raw MCP tools. Each Tool's description, JSON Schema, and annotations carry the portable operation contract; negotiated server instructions (modern discovery or the legacy initialize handshake) supply the complete shared protocol to clients that expose them, but critical Tool rules do not depend on that optional hint alone.
3. `docs/agent-contract.md` is the deliberately short managed global rules block. It contains stable authority and routing rules, not the full operation manual.
4. `hooks/` owns Context Bootstrap, Memory Route, and Memory Closeout, plus host-native payload projection and ownership-aware merging.
5. `host_setup.py` and `host_adapters.py` reconcile each supported host without changing unrelated configuration.
6. `installer.py` provides `install`, `status`, `repair`, `upgrade`, and `uninstall`; its state file is observational, while live configuration and host diagnostics remain authoritative.

`keepygaga-mcp` is the stable MCP entrypoint. Host registrations created from a published tool install do not point at a checkout-specific Python interpreter. `keepygaga hook run` is the stable built-in Hook entrypoint.

## Memory model

The only source of truth is the live Markdown allowlist below Memory Root. Fixed pages are `profile.md` and `preferences.md`; dynamic pages are direct Markdown children of the independently bounded `topics`, `areas`, and `people` scopes. Canonical frontmatter is `name`, `description`, and `aliases`; body lines are independent `[stated]` or `[observed]` Facts with an optional Store-owned local last-write date. Fact content and route metadata must remain one physical Unicode line. The terminal ` [YYYY-MM-DD]` form is reserved for that date; other legacy undated Facts remain valid.

Every call rereads its live files. Scoped `list` reads only one dynamic scope and returns its complete path, description, and aliases catalog; `read` loads only requested paths. Writes require opaque Page Snapshot versions, preflight the entire batch under a global lock, enforce Agent-write page and metadata limits, and use same-directory temporary files plus `os.replace`. Memory Root is checked without resolving away a final symlink or junction; page reads reject symlinks and non-regular files. Keepygaga does not sandbox against another process running as the same filesystem user: such a process can already read, replace, or rename Memory Root directly and is outside the Store trust boundary. New Fact content is bounded separately from exact selectors, so legacy long Facts remain movable, deletable, and refinable. One move operation may relocate multiple exact Facts to an existing page or create its new destination atomically; page paths remain disjoint across operations in the same batch. Changed pages are canonicalized; unchanged pages retain their bytes. Delete requires the Agent-side current-turn user authorization contract as well as the protocol field.

Memory is context evidence, not authority or executable instruction. Project state stays in project-owned sources. Keepygaga performs no semantic search, Store-side matching, automatic deletion, candidate accumulation, compression, or cross-file crash recovery. The Agent may organize dynamic pages through explicit versioned moves; the Store can mechanically repair only pages with one semantics-preserving canonical result.

## Hook model

The product owns three semantic capabilities:

- Context Bootstrap loads Profile, Preferences, and fixed descriptions of the three dynamic memory scopes at a supported session boundary. Dynamic Route Catalogs are fetched on demand with scoped `list`.
- Memory Route injects a small per-turn routing reminder and stores only boolean transient signals.
- Memory Closeout emits a deduplicated reminder only when the turn indicates project or durable-memory work.

Adapters project those capabilities into native host events. The merger removes only commands matching Keepygaga-owned current or legacy markers, then preserves all unrelated entries. Unsupported host capabilities are omitted honestly; no temporary or downloaded Hook implementation is synthesized.

## Host reconciliation

Supported adapters are Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI. Setup order is MCP, Agent Contract, Hooks. Each stage uses preflight data and detects concurrent changes; partial commits report applied components and recovery evidence. Repeated setup converges to `no_op`.

Uninstall removes only the `keepygaga` MCP registration, managed Contract block, and Keepygaga-owned Hook entries. It preserves Memory Root, product configuration, install package, unrelated MCP registrations, and unrelated Hooks. Repeated uninstall converges to `no_op`.

Legacy external-Hook arguments remain private compatibility seams for deterministic migration tests, but they are not part of the public CLI or required runtime. New installations use built-in Hooks and stable launchers.

## Installation and versioning

The canonical distribution path is a tagged GitHub Release installed as a `uv` tool. Source checkouts remain a contributor workflow, not the user update channel. Tag workflows inspect wheel and sdist inventories, persist one immutable distribution bundle before exposing individual artifacts, and verify the published asset set before making the Release public. PyPI is not an active release channel; enabling it later requires trusted publishing and must consume the same verified GitHub assets rather than rebuilding them.

Five version axes are intentionally independent: application release, Agent Contract, Hook protocol, installer-state schema, and memory schema. A product patch need not rewrite global rules; a Contract or Hook change can be repaired independently.

Default configuration, data, and installer-state paths are platform-native. The state file helps discover previously selected hosts and install channel but never overrides live host files or `keepygaga.toml`.

## Verification boundary

Repository tests and temporary homes establish only Config-tested behavior: projection, preservation, idempotency, failure routing, schemas, and artifact inventory. Live-verified means the real host or its official diagnostic confirms the installed `keepygaga` registration and exactly eight tools. Configuration success alone must not be described as live verification.

## Threat model

Filesystem boundaries are enforced by path allowlists, no-follow page reads on supported platforms, symlink/junction checks, locks, compare-and-swap checks, private creation modes on POSIX, and atomic replacement. The Agent and host remain responsible for current user intent. Markdown inside the selected Memory Root is trusted local input and may contain sensitive personal data.
