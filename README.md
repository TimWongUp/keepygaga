# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**One private Obsidian vault for the core memory every coding agent should share.**

Keepygaga gives Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI the same user-owned core memory instead of leaving durable identity and preferences in separate host silos. The source of truth is readable Markdown in one private Memory Root, preferably inside an Obsidian vault; any Markdown editor remains compatible.

The product has three deliberately separate surfaces:

- **Obsidian or another Markdown editor** is where people inspect, correct, and organize memory.
- **MCP, Hooks, and the Agent Contract** let agents read and update that memory under explicit constraints.
- **The `keepygaga` CLI** is a thin installation and operations control plane for host wiring, status, diagnostics, repair, upgrades, and uninstall. It is not a daily memory browser or editor.

Keepygaga ships the complete runtime: an eight-tool MCP server, a concise global Agent Contract, built-in cross-host Hooks, and the CLI control plane. It does not require a database, embeddings, a source checkout, or an external Hook runtime. Obsidian is the recommended human interface, not a runtime dependency.

Core memory contains `profile.md`, `preferences.md`, and direct pages below `topics/`, `areas/`, and `people/`. Project details and current state remain in their repository or live source; Keepygaga keeps only project locations and completed major milestones.

Host-native memories can continue to own host-specific conversation recall and project learning. Keepygaga owns the small set of stable user facts that should follow the user across hosts.

The public MCP surface is exactly `list`, `read`, `create`, `add`, `update`, `move`, `rename`, and `delete`.

### Upgrading to 0.5

Version 0.5 changes each `move` operation from a single `fact` field to a required `facts` array. Clients that cache MCP schemas must reconnect or refresh the Tool schema after upgrading, then group all exact Facts for one source/destination pair into that array. This is an MCP request-shape change only; the Markdown memory format and existing memory files are unchanged.

## Install

Requirements: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```shell
uv tool install keepygaga
keepygaga install
```

Interactive installation first offers a Memory Root path, then detects available hosts without selecting them on the user's behalf. Point it at an existing `agents-memory` tree to connect another Agent to the same memory. Once configured, later installs reuse that root automatically. Automation must name every target explicitly:

```shell
keepygaga install --yes --host codex --host claude-code
```

Supported adapters are Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI. Each adapter manages only its `keepygaga` MCP registration, the Keepygaga-owned Agent Contract block, and Keepygaga-owned Hook entries. Unrelated host configuration is preserved.

The default configuration and memory paths are platform-native. To reuse an existing private memory tree non-interactively, pass `--memory-root` during the first install. Do not place the memory tree in a public or automatically published directory.

## Operate

```shell
keepygaga status
keepygaga repair --yes
keepygaga upgrade --yes
keepygaga doctor --json
keepygaga uninstall --yes
```

`status` treats the install-state file as discovery data only and reports when live host verification is still required. `repair` reconciles recorded hosts from their current configuration. `upgrade` installs the latest published release through `uv` and then repairs recorded hosts. `uninstall` removes only Keepygaga host wiring; it preserves the configuration and memory tree.

Advanced deterministic host commands remain available as `keepygaga host setup|uninstall HOST`.

## How integration works

- `keepygaga-mcp` is the stable MCP launcher used by host registrations.
- The short managed Agent Contract contains only durable safety and routing rules.
- The full read, convergence, mutation, conflict, and receipt protocol is delivered through MCP `initialize.instructions`.
- Built-in Context Bootstrap, Memory Route, and Memory Closeout Hooks are projected into each host's native event schema.
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

## Security and license

Memory files are trusted local input and may contain personal data. Keep the memory root private, review changes before committing them anywhere, and report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/TimWongUp/keepygaga/security/advisories/new).

MIT licensed. See [LICENSE](LICENSE).
