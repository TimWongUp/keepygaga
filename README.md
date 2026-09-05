# Keepygaga

<p align="center">
  <img src="docs/assets/keepygaga-banner.png" alt="Keepygaga — a small, deliberate core memory shared by every coding agent" width="100%">
</p>

[English](README.md) | [简体中文](README.zh-CN.md)

**A small, deliberate core memory shared by every coding agent.**

AI agents do not get better by remembering everything. If every conversation, temporary state, and project detail is pushed into long-term memory, useful facts are buried under stale and irrelevant context. Memory without selection is noise.

Keepygaga keeps only a small set of durable facts that remain useful across tasks: who the user is, how they want an Agent to work, and a few ongoing topics, projects, responsibilities, or relationships. Temporary state stays in the current conversation or its direct source, such as a calendar, task manager, project documentation, issue tracker, or Git history. A fact enters core memory only when it has been deliberately judged useful across tasks.

That carefully selected core memory belongs to the user and follows them across Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI instead of being trapped in separate host silos. Its source of truth is readable Markdown in one private Memory Root, preferably inside an Obsidian vault; any Markdown editor remains compatible.

The product has three deliberately separate surfaces:

- **Obsidian or another Markdown editor** is where people inspect, correct, and organize memory.
- **MCP, Hooks, and the Agent Contract** let agents read and update that memory under explicit constraints.
- **The `keepygaga` CLI** is a thin installation and operations control plane for host wiring, status, diagnostics, repair, upgrades, and uninstall. It is not a daily memory browser or editor.

Keepygaga ships the complete runtime: an eight-tool MCP server, a concise global Agent Contract, built-in cross-host Hooks, and the CLI control plane. It does not require a database, embeddings, a source checkout, or an external Hook runtime. Obsidian is the recommended human interface, not a runtime dependency.

Core memory contains `profile.md`, `preferences.md`, and direct pages below `topics/`, `areas/`, and `people/`. Ongoing projects share the optional canonical index `areas/projects.md`, created with its first project Fact: one Fact per project holds a brief, its canonical Authority, and its latest verified integrated outcome and release status when available, with later changes replacing that Fact and no major-milestone threshold. For Git projects, verify the canonical remote primary branch; record a published version only when a published Release points to a tag commit containing that outcome. Complete history, terminology, architecture, operating guides, decisions, and current state remain in the repository or another direct project source.

Host-native memories can continue to own host-specific conversation recall and project learning. Keepygaga owns the small set of stable user facts that should follow the user across hosts. A durable instruction admitted to source selection has exactly two possible owners: `preferences.md` when every connected Agent should follow it, or one host's effective global-rules entry when only that Agent should. Prose style and code style do not determine ownership by themselves. When the user has not specified the intended scope, the Agent must ask first, and one meaning may have only one source. Project rules stay in the project Authority and do not enter this choice.

The public MCP surface is exactly `list`, `read`, `create`, `add`, `update`, `move`, `rename`, and `delete`.

Session bootstrap injects only `profile.md`, `preferences.md`, a shared routing rule, and descriptions of the three dynamic scopes. Agents treat those descriptions as first-stage semantic routes: when a task depends on covered information that the current request or a live direct source does not already provide, they call `list` for that scope and select pages from the returned path, description, and aliases before reading them. New or semantically updated Facts receive a Store-owned local date suffix; existing undated Facts remain readable and upgrades do not rewrite the Memory Root.

Contract 3 users with existing project pages should follow the [project-index migration](docs/operations.md#project-index-migration) before their next project-memory write under the current Agent Contract.

## Install

Requirements: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

### Agent-guided installation (recommended)

Give the Agent host you are currently using this one sentence:

> Quickly install or update Keepygaga for the Agent you are running in now from the latest official Release at https://github.com/TimWongUp/keepygaga: automatically choose install, update, current-host repair, or no action; preserve existing configuration and memory; ask me only for first-time initialization, a conflict, or a possible overwrite; then report the result and any restart requirement.

The [Agent Fast Install To-do](docs/agent-install.md) is the authoritative procedure for this path. It checks the installed version before downloading, limits work to the selected lifecycle branch and current Agent, and reuses existing data. The heavier [Home Page source migration](docs/source-migration.md) is loaded only for first initialization or a concrete duplicate. Host-native memory remains unchanged; when requested, the Agent supplies current official host documentation for user-managed configuration.

### Manual installation

Download the `keepygaga-X.Y.Z-py3-none-any.whl` asset and `SHA256SUMS` from the same [latest GitHub Release](https://github.com/TimWongUp/keepygaga/releases/latest) to private, non-symlinked paths. Immediately before installation, verify the exact wheel's SHA-256 entry and execute that same absolute path, replacing `X.Y.Z` below with the release version:

```shell
uv tool install /absolute/private/path/keepygaga-X.Y.Z-py3-none-any.whl
uv tool update-shell
```

Restart the terminal so the tool directory is on `PATH`, then run `keepygaga install`.

The checksum detects corruption or an asset mismatch. It is not a signature, provenance proof, independent publisher authentication, or verification of dependencies resolved from the package index.

Interactive installation first offers a Memory Root path, then detects available hosts without selecting them on the user's behalf. Point it at an existing `agents-memory` tree to connect another Agent to the same memory. Once configured, later installs reuse that root automatically. Automation must name every target explicitly:

```shell
keepygaga install --yes --host codex --host claude-code
```

Supported adapters are Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI. Each adapter manages only its `keepygaga` MCP registration, the Keepygaga-owned Agent Contract block, and Keepygaga-owned Hook entries. Unrelated host configuration is preserved.

The default configuration and memory paths are platform-native. To reuse an existing private memory tree non-interactively, pass `--memory-root` during the first install. Do not place the memory tree in a public or automatically published directory.

New installations include five optional memory-capacity settings with the current defaults and adjustment notes. Existing configuration files are never rewritten. Edit the live `config.toml`; the next MCP call reloads these Store-only limits without requiring a schema refresh:

```toml
[memory.limits]
# Raise for richer profile/preferences; lower to reduce baseline context.
fixed_page_chars = 2000
# Raise for fewer, larger routed pages; lower to encourage earlier splitting.
dynamic_page_chars = 5000
# Raise to allow more topic pages; lowering never deletes existing pages.
topics_pages = 50
# Raise to allow more area pages; lowering never deletes existing pages.
areas_pages = 50
# Raise to allow more people pages; lowering never deletes existing pages.
people_pages = 100
```

Every value must be a positive integer. Lower limits report existing excess through Doctor and constrain later growth; they do not delete or rewrite memory. The bounded repair input is derived as twice `dynamic_page_chars`.

## Operate

```shell
keepygaga status
keepygaga status --latest-version vX.Y.Z --host codex
keepygaga repair --yes
keepygaga doctor --json
keepygaga uninstall --yes
```

`status` treats the install-state file as discovery data only and reports when live host verification is still required. With the latest official release tag and current host, it returns a read-only lifecycle action: `update`, `initialize`, `activate`, `repair`, `no_op`, or `manual_review`. A missing launcher is the separate clean-install case. `repair` reconciles recorded hosts from their current configuration. `uninstall` removes only Keepygaga host wiring; it preserves the configuration and memory tree.

For a current-host-only update, download the newer wheel and matching `SHA256SUMS`, rehash the exact absolute wheel path, set `UV_TOOL_DIR` to the `lifecycle.tool_root` returned by planned `status` for that command, run `uv tool install --force /absolute/private/path/keepygaga-X.Y.Z-py3-none-any.whl`, then run `keepygaga install --yes --host HOST`. Run `keepygaga repair --yes` instead only when you intentionally want to reconcile every recorded host.

Advanced deterministic host commands remain available as `keepygaga host setup|uninstall HOST`.

## How integration works

- `keepygaga-mcp` is the stable MCP launcher used by host registrations.
- The short managed Agent Contract contains only durable safety and routing rules.
- The full read, convergence, mutation, conflict, and receipt protocol is delivered through negotiated MCP server instructions (modern discovery or the legacy initialize handshake).
- Built-in Context Bootstrap and stateless Memory Route reminders are projected through each host's supported native events. Routing reminders include completion checks; there is no PostToolUse closeout Hook. Unsupported surfaces use documented fallbacks; Grok uses the managed Agent Contract for memory guidance.
- Application, Agent Contract, Hook protocol, installer state, and memory schema versions evolve independently.

Configuration-level tests prove projection, preservation, idempotency, and failure boundaries. A host is live-verified only after its real client or official diagnostic confirms the `keepygaga` registration and all eight tools.

## Development

```shell
uv sync
uv run pytest -q
uv run ruff check .
uv run pyright
uv run python scripts/smoke_mcp_server.py
uv build
uv run python scripts/check_distribution.py dist/*
```

The `keepygaga-knowledge` sibling project is separate and is neither packaged nor imported by Keepygaga. See [Architecture](docs/architecture.md), [Operations](docs/operations.md), and [Contributing](CONTRIBUTING.md).

## Acknowledgements

Keepygaga's core memory design was inspired by Claude Code's memory system.

Thanks also to the Claude Code team for their pioneering work on AI memory.

## Security and license

Memory files are trusted local input and may contain personal data. Keep the memory root private, review changes before committing them anywhere, and report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/TimWongUp/keepygaga/security/advisories/new).

MIT licensed. See [LICENSE](LICENSE).
