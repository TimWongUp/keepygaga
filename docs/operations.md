# Keepygaga Operations

## User control plane

Install a published release with `uv tool install keepygaga`, then run `keepygaga install`. Non-interactive installation requires `--yes` and one or more explicit `--host` values. Use an explicit `--memory-root` only when reusing a private, trusted tree.

- `keepygaga status` reads live config and Doctor, compares recorded Contract versions, and labels host checks that still require live verification.
- `keepygaga repair --yes` reruns idempotent reconciliation for recorded hosts.
- `keepygaga upgrade --yes` upgrades the published `uv` tool and then repairs recorded hosts.
- `keepygaga uninstall --yes` removes recorded host wiring while preserving config and memory.
- `keepygaga host setup|uninstall HOST` remains the deterministic expert path.

Install state is discovery evidence only. If it disagrees with a host's live configuration, the host file and official diagnostic win.

## Repository verification

Run the smallest relevant tests first, then the complete gates:

```shell
uv run pytest -q
uv run ruff check .
uv run pyright
uv run python scripts/smoke_mcp_server.py
uv build
uv run python scripts/check_distribution.py dist/*
```

The MCP smoke must prove the exact eight-tool surface, initialize instructions, a real versioned mutation cycle, and Doctor. Distribution inspection must prove that built-in Hook and MCP instruction assets are present and that split Knowledge/dashboard code is absent.

Host-adapter changes additionally need temporary-home setup/setup and uninstall/uninstall cycles. The second invocation must be `no_op`; unrelated MCP registrations, global-rule bytes outside the managed block, and unrelated Hooks must survive. Corrupt files, duplicate keys, symlinks, concurrent drift, and partial-commit evidence remain required risk cases.

Temporary homes prove only Config-tested behavior. Real host verification must inspect the active `keepygaga` registration and all eight tools. Grok and Hermes should use their official MCP diagnostics when available.

## Hook diagnostics

Built-in Hooks execute through `keepygaga --config CONFIG_PATH hook run context|route|closeout`. Verify that projected commands use the installed launcher and current absolute config path. Context failures return an explicit bootstrap-error payload; they must not silently substitute another memory source. Route state is transient, contains no raw prompt, and expires. Closeout is deduplicated and respects host re-entry signals.

If Hook setup fails, inspect the target host's native event schema, the Keepygaga ownership markers, the stable launcher, and the configured Memory Root. Do not add an external Hook runtime as a fallback.

## Failure routing

- Invalid config or Memory Root: run Doctor, fix the exact live path or malformed page, and retry. Do not initialize over invalid existing content.
- `write_conflict`: reread the returned `latest` snapshot when present and reclassify; never retry an old version unchanged.
- `partial_commit`: treat reported components and backups as live evidence, inspect them, then rerun the same idempotent operation.
- Contract marker corruption or duplicate managed blocks: fail closed and repair the exact host rules file manually.
- MCP verification failure: inspect the stable launcher, absolute config path, and returned recovery data.
- Hook bootstrap error: report it; do not guess or use a different retrieval system.
- Upgrade succeeded but repair failed: the package is new while host projection may be old; resolve the reported host error and run `keepygaga repair --yes`.

Doctor reports non-sensitive metadata only. `ok` means applicable checks passed, `warning` requires reading the individual check, and `error` blocks setup. Dynamic-page or home-page capacity warnings may be soft; permissions, malformed content, identity conflicts, or unwritable paths are blocking.

## Release

Release tags are `v<application-version>`. The tag workflow reruns tests and static checks, builds wheel and sdist, verifies inventory, creates a GitHub Release, and publishes to PyPI using the repository's `pypi` trusted-publisher environment. Before the first tag, protect the `v*` tag namespace, require approval on the `pypi` environment, and configure the PyPI trusted publisher; never add a publishing token to the repository.
