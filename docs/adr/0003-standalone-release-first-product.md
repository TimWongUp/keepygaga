# ADR 0003: Make Keepygaga a standalone release-first product

- Status: Accepted
- Date: 2026-08-27
- Amended: 2026-09-03 — GitHub Release is canonical; PyPI is inactive.

## Context

Keepygaga previously required a source checkout, registered checkout-specific Python commands, and delegated Hook behavior to an external runtime. That made installation, updates, ownership, migration, and user-facing support span multiple projects. The detailed Agent protocol also made every global rules projection large and coupled product releases to rule rewrites.

## Decision

Keepygaga will publish one installable package that owns its MCP server, stable launchers, short Agent Contract, complete MCP initialize instructions, three semantic Hooks, host adapters, diagnostics, and install/status/repair/upgrade/uninstall control plane.

The CLI remains an installation and operations control plane rather than growing into a daily memory client. People inspect, correct, and organize the shared Memory Root in a private Obsidian vault or another Markdown editor; Agents access it through MCP, Hooks, and the Agent Contract. Obsidian is recommended but is not a runtime dependency.

New host registrations use `keepygaga-mcp`; built-in Hook projections use `keepygaga hook run`. The external Agent Hook Runtime and `agent-runtime-config` are not runtime dependencies. The install-state file is observational, with live configuration remaining authoritative. Tagged GitHub Releases are the supported distribution channel. Application, Contract, Hook, installer-state, and memory versions evolve independently.

## Consequences

Users can install and update without a source checkout or coordinating another repository. Keepygaga becomes responsible for cross-host Hook compatibility, migrations, artifact inventory, and release automation. The managed global Contract becomes smaller, while clients must preserve MCP initialize instructions. Legacy owned Hook entries are removed during reconciliation, but unrelated external runtime files and configuration are not deleted.

Source checkout installation remains available for contributors, not as the normal product channel. PyPI is not active; enabling it later requires trusted-publisher configuration outside the repository and must reuse the verified GitHub Release artifacts.

Keepygaga does not need a parallel CLI browsing or editing experience. This keeps Markdown as the user-owned interface and avoids duplicating Obsidian while the product focuses on safe cross-host access and lifecycle management.
