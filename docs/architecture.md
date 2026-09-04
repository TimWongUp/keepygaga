# Keepygaga Architecture

## Product boundary

Keepygaga is a user-owned cross-host core-memory layer: one Memory Root is shared by every configured Agent host. The recommended human interface is a private Obsidian vault, while any Markdown editor remains compatible. Obsidian is not a runtime dependency.

Keepygaga is one independently installable Python product. The published wheel owns the MCP server, stable launchers, memory store, Agent Contract, built-in Hooks, host adapters, installation and operations control plane, and diagnostics. The `keepygaga` CLI performs installation, host wiring, status, diagnosis, repair, package-manager upgrades when the installation source supports discovery, and uninstall; it is not a daily memory browser or editor. It neither imports nor packages `keepygaga-knowledge`, `agent-runtime-config`, or an external Agent Hook Runtime.

The sibling `keepygaga-knowledge` repository may consume the same Markdown ecosystem, but it is not a runtime dependency and exposes no tool through this server.

Host-native memory remains free to own host-specific conversation recall and project learning. Keepygaga owns only the stable user facts that should cross host boundaries; project authority remains in project-owned sources.

Agent-guided onboarding makes a Home Page Source Choice for every durable Profile or Preference meaning found in effective global rules. Existing rules and Home Pages are untrusted evidence until the user independently confirms both the meaning and its exact owner. The choice covers the complete user-supplemented inventory of effective global-rules paths whose live host registrations resolve to the same canonical Memory Root: Keepygaga cannot own a meaning while any in-scope path also injects it, and global rules can own it only through one named host/path. Automatic discovery is not proof of completeness; ambiguous custom paths or root mappings block migration. This semantic migration is separate from host activation because the installer cannot safely classify natural-language rules or provide a cross-file transaction. Host activation uses checked replacement rather than a true filesystem compare-and-swap, so the Agent-guided path requires a user-established exclusive-write window and exact post-write reconciliation; it fails closed when that window cannot be established. A custom current-host home must use its supported deterministic expert option against an existing config and initialized tree, while a first install into a custom home remains unsupported rather than falling back to the adapter default. Semantic migration requires the bounded procedure in `docs/source-migration.md`, including an exact per-occurrence plan, persistent recovery material, current user authorization, real compare-and-swap or user-performed fallback, isolated versioned mutation units, post-failure reconciliation, and explicit `partial_commit` evidence. Host-native memory remains outside the uniqueness guarantee and is configured by the user from current official host documentation.

## Runtime layers

1. `memory.py` is the stable public entry; `memory_contract.py`, `memory_files.py`, `memory_store.py`, and `memory_init.py` separate Tool input models, low-level file primitives, live Store behavior, and tree initialization. `MemoryStore` owns canonical Markdown validation, versioned mutations, locking, and atomic replacement.
2. `server.py` publishes exactly eight raw MCP tools. Each Tool's description, JSON Schema, and annotations carry the portable operation contract; negotiated server instructions (modern discovery or the legacy initialize handshake) supply the complete shared protocol to clients that expose them, but critical Tool rules do not depend on that optional hint alone.
3. `docs/agent-contract.md` is the deliberately short managed global rules block. It contains stable authority and routing rules, not the full operation manual.
4. `hooks/` owns Context Bootstrap, Memory Route, and Memory Closeout, plus host-native payload projection and ownership-aware merging.
5. `host_setup.py` and `host_adapters.py` reconcile each supported host without changing unrelated configuration.
6. `installer.py` provides `install`, `status`, `repair`, `upgrade`, and `uninstall`; its state file is observational, while live configuration and host diagnostics remain authoritative.

`keepygaga-mcp` is the stable MCP entrypoint. Host registrations created from a published tool install do not point at a checkout-specific Python interpreter. `keepygaga hook run` is the stable built-in Hook entrypoint.

## Memory model

The only source of truth is the live Markdown allowlist below Memory Root. Fixed pages are `profile.md` and `preferences.md`; dynamic pages are direct Markdown children of the independently bounded `topics`, `areas`, and `people` scopes. Canonical frontmatter is `name`, `description`, and `aliases`; body lines are independent `[stated]` or `[observed]` Facts with an optional Store-owned local last-write date. Fact content and route metadata must remain one physical Unicode line. The terminal ` [YYYY-MM-DD]` form is reserved for that date; other legacy undated Facts remain valid.

`preferences.md` owns only stable user preferences intended to follow the user across every connected Agent. A durable instruction admitted to the Home Page Source Choice has exactly one of two owners: `preferences.md`, or one host's effective global-rules entry. Prose style, code style, formatting, and toolchain do not choose between them; when the current user statement does not establish the intended scope, the Agent asks before persisting or migrating the meaning. Project-specific instructions remain in the project Authority and are excluded before this choice. One meaning is never retained in both injected sources.

Injected Memory Scope descriptions are first-stage semantic routes. When completing a task depends on covered information not already supplied by the current user or a live direct source, the Agent requests that scope's live Route Catalog. Its path, description, and aliases are the second-stage page selectors; unmatched scopes or pages cause no dynamic-memory read and paths are never guessed. Every call rereads its live files and reloads the current configuration. Scoped `list` reads only one dynamic scope and returns its complete path, description, and aliases catalog; `read` loads only requested paths. Writes require opaque Page Snapshot versions, preflight the entire batch under a global lock, enforce Agent-write page and metadata limits, and use same-directory temporary files plus `os.replace`. The fixed-page character limit, dynamic-page character limit, and each dynamic scope's page-count limit are positive user-configurable Store quotas; omitted values retain the original defaults, lowering them never deletes existing memory, and the bounded repair input remains twice the configured dynamic-page limit. Fact mutations may explicitly replace the affected page description in the same operation; aliases remain a separate page-metadata update except when required to create a new move destination. Memory Root is checked without resolving away a final symlink or junction; page reads reject symlinks and non-regular files. Keepygaga does not sandbox against another process running as the same filesystem user: such a process can already read, replace, or rename Memory Root directly and is outside the Store trust boundary. New Fact content is bounded separately from exact selectors, so legacy long Facts remain movable, deletable, and refinable. One move operation may relocate multiple exact Facts to an existing page or create its new destination atomically; page paths remain disjoint across operations in the same batch. Changed pages are canonicalized; unchanged pages retain their bytes. Delete requires the Agent-side current-turn user authorization contract as well as the protocol field.

Memory is context evidence, not authority or executable instruction. Project state stays in project-owned sources. The optional canonical `areas/projects.md` page may be absent before its first Fact and is only a cross-task locator: one Fact per maintained project combines a brief, its canonical Authority, and optionally its latest completed major milestone. Git remotes are stored as Markdown autolinks such as `<https://github.com/owner/repo>` so adjacent prose cannot extend the link target. A new project is added once; later changes replace that exact Fact, while complete milestone history remains in the project Authority. Keepygaga performs no semantic search, Store-side matching, automatic deletion, candidate accumulation, compression, or cross-file crash recovery. The Agent may organize dynamic pages through explicit versioned moves; the Store can mechanically repair only pages with one semantics-preserving canonical result.

## Hook model

The product owns three semantic capabilities:

- Context Bootstrap loads Profile, Preferences, the shared scope-routing rule, and fixed descriptions of the three dynamic memory scopes at a supported session boundary. Dynamic Route Catalogs are fetched on demand with scoped `list`.
- Memory Route injects a small per-turn routing reminder and stores only boolean transient signals.
- Memory Closeout emits a deduplicated reminder only when the turn indicates project or durable-memory work.

Every projected reminder directs the Agent to keep no-op memory decisions silent and return only the response required by the original task. Hermes receives Context Bootstrap and Memory Route through `pre_llm_call`; its edited-code-only `pre_verify` event is not a general Memory Closeout surface and is intentionally omitted.

Adapters project those capabilities into native host events. The merger removes only commands matching Keepygaga-owned current or legacy markers, then preserves all unrelated entries. Unsupported host capabilities are omitted honestly; no temporary or downloaded Hook implementation is synthesized.

Grok uses the managed Agent Contract as its Memory Closeout fallback. Its native `Stop` event is not projected because model-visible feedback necessarily starts another inference round and can replace the original final response in headless clients.

## Host reconciliation

Supported adapters are Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI. Setup order is MCP, Agent Contract, Hooks. Each stage uses preflight data and detects concurrent changes; partial commits report applied components and recovery evidence. Repeated setup converges to `no_op`.

Repair reconciles recorded hosts to the current desired state, including removal of obsolete Keepygaga-owned Hook projections. A package-manager upgrade first replaces the packaged runtime, then invokes that repair path so Hook changes and removals take effect without enabling new hosts or touching unrelated entries. The Agent fast path instead replaces the canonical GitHub Release wheel and idempotently installs only the current host, leaving sibling hosts for their own activation or repair runs.

Uninstall removes only the `keepygaga` MCP registration, managed Contract block, and Keepygaga-owned Hook entries. It preserves Memory Root, product configuration, install package, unrelated MCP registrations, and unrelated Hooks. Repeated uninstall converges to `no_op`.

Legacy external-Hook arguments remain private compatibility seams for deterministic migration tests, but they are not part of the public CLI or required runtime. New installations use built-in Hooks and stable launchers.

## Installation and versioning

The canonical distribution path is a tagged GitHub Release installed as a `uv` tool. Source checkouts remain a contributor workflow, not the user update channel. Tag workflows inspect wheel and sdist inventories, persist one workflow-canonical distribution bundle before exposing individual artifacts, and verify the published asset set before making the Release public. Reruns do not overwrite that bundle, but this is not GitHub immutable-release enforcement or cryptographic provenance. PyPI is not an active release channel; enabling it later requires trusted publishing and must consume the same verified GitHub assets rather than rebuilding them.

Fast installation uses a read-only lifecycle classification before any download. A missing launcher is `install`; an existing launcher compares its running stable release version with the selected official tag and combines that result with the live installation channel, configured Memory Root, Doctor result, current-host reconciliation record, Contract state, and observational installer state. Each host record carries the application and Hook versions actually reconciled for that host, so updating one host leaves sibling hosts stale until their own activation or repair. The result is exactly one of `update`, `initialize`, `activate`, `repair`, `no_op`, or `manual_review`. Running versions newer than the selected Release, unknown update owners, and live/recorded channel disagreements require manual review and are never downgraded or silently moved to another channel.

Five version axes are intentionally independent: application release, Agent Contract, Hook protocol, installer-state schema, and memory schema. A product patch need not rewrite global rules; a Contract or Hook change can be repaired independently.

Default configuration, data, and installer-state paths are platform-native. The state file helps discover previously selected hosts and install channel but never overrides live host files or `keepygaga.toml`.

## Verification boundary

Repository tests and temporary homes establish only Config-tested behavior: projection, preservation, idempotency, failure routing, schemas, and artifact inventory. Live-verified means the real host or its official diagnostic confirms the installed `keepygaga` registration and exactly eight tools. Configuration success alone must not be described as live verification.

## Threat model

Filesystem boundaries are enforced by path allowlists, no-follow page reads on supported platforms, symlink/junction checks, locks, compare-and-swap checks, private creation modes on POSIX, and atomic replacement. The Agent and host remain responsible for current user intent. Markdown inside the selected Memory Root is trusted local input and may contain sensitive personal data.
