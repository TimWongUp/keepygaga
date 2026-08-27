# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**A small, local-first long-term memory product for AI agents.**

Keepygaga stores a deliberately small set of durable user facts in readable Markdown. It ships the complete runtime: an eight-tool MCP server, a concise global Agent Contract, built-in cross-host Hooks, and an installation control plane. It does not require a database, embeddings, a source checkout, or an external Hook runtime.

Core memory contains `profile.md`, `preferences.md`, and direct pages below `topics/`, `areas/`, and `people/`. Project details and current state remain in their repository or live source; Keepygaga keeps only project locations and completed major milestones.

The public MCP surface is exactly `list`, `read`, `create`, `add`, `update`, `move`, `rename`, and `delete`.

## Install

Requirements: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```shell
uv tool install keepygaga
keepygaga install
```

Interactive installation detects available hosts but does not select them without confirmation. Automation must name every target explicitly:

```shell
keepygaga install --yes --host codex --host claude-code
```

Supported adapters are Codex, Claude Code, WorkBuddy, Grok, Hermes, and Antigravity CLI. Each adapter manages only its `keepygaga` MCP registration, the Keepygaga-owned Agent Contract block, and Keepygaga-owned Hook entries. Unrelated host configuration is preserved.

The default configuration and memory paths are platform-native. To reuse an existing private memory tree, pass `--memory-root` during the first install. Do not place the memory tree in a public or automatically published directory.

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
