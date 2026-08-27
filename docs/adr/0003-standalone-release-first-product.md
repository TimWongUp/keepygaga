# ADR 0003: Make Keepygaga a standalone release-first product

- Status: Accepted
- Date: 2026-08-27

## Context

Keepygaga previously required a source checkout, registered checkout-specific Python commands, and delegated Hook behavior to an external runtime. That made installation, updates, ownership, migration, and user-facing support span multiple projects. The detailed Agent protocol also made every global rules projection large and coupled product releases to rule rewrites.

## Decision

Keepygaga will publish one installable package that owns its MCP server, stable launchers, short Agent Contract, complete MCP initialize instructions, three semantic Hooks, host adapters, diagnostics, and install/status/repair/upgrade/uninstall control plane.

New host registrations use `keepygaga-mcp`; built-in Hook projections use `keepygaga hook run`. The external Agent Hook Runtime and `agent-runtime-config` are not runtime dependencies. The install-state file is observational, with live configuration remaining authoritative. Tagged GitHub/PyPI releases are the supported update channel. Application, Contract, Hook, installer-state, and memory versions evolve independently.

## Consequences

Users can install and update without a source checkout or coordinating another repository. Keepygaga becomes responsible for cross-host Hook compatibility, migrations, artifact inventory, and release automation. The managed global Contract becomes smaller, while clients must preserve MCP initialize instructions. Legacy owned Hook entries are removed during reconciliation, but unrelated external runtime files and configuration are not deleted.

Source checkout installation remains available for contributors, not as the normal product channel. The first PyPI release still requires trusted-publisher environment configuration outside the repository.
