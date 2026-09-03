# Keepygaga Operations

## Installation and operations control plane

The `keepygaga` CLI installs and maintains the product; it is not the routine interface for browsing or editing memory. Users inspect, correct, and organize the shared Memory Root in Obsidian or another Markdown editor, while Agents use MCP and Hooks.

Download `keepygaga-X.Y.Z-py3-none-any.whl` from the latest GitHub Release, install it with `uv tool install ./keepygaga-X.Y.Z-py3-none-any.whl`, and run `uv tool update-shell`. Restart the terminal so the tool directory is on `PATH`, then run `keepygaga install`. Interactive installation prompts for the Memory Root before host selection. An existing configured root is reused automatically when adding another host. Non-interactive first installation requires `--yes`, one or more explicit `--host` values, and an explicit `--memory-root` only when reusing a private, trusted tree.

- `keepygaga status` reads live config and Doctor, compares recorded Contract versions, and labels host checks that still require live verification.
- `keepygaga repair --yes` reruns idempotent desired-state reconciliation for recorded hosts, including removal of obsolete Keepygaga-owned Hook entries.
- `keepygaga uninstall --yes` removes recorded host wiring while preserving config and memory.
- `keepygaga host setup|uninstall HOST` remains the deterministic expert path.

Install state is discovery evidence only. If it disagrees with a host's live configuration, the host file and official diagnostic win.

To upgrade through the current GitHub Release channel, download the newer wheel, run `uv tool install --force ./keepygaga-X.Y.Z-py3-none-any.whl`, then run `keepygaga repair --yes` to apply changed or removed host projections. `keepygaga upgrade --yes` is available only when the installation's package-manager source can resolve a newer release; it is not the update path for a versioned GitHub Release wheel.

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

The MCP schema tests must prove the exact eight-tool surface, closed input schemas, action-oriented descriptions, and read/destructive/idempotent/open-world annotations. The MCP smoke must prove server instructions through modern discovery and the legacy initialize handshake, a real versioned mutation cycle, and Doctor. Distribution inspection must prove that built-in Hook and MCP instruction assets are present and that split Knowledge/dashboard code is absent. Ruff gates cyclomatic complexity at 10 so orchestration functions remain split at observable workflow boundaries.

Host-adapter changes additionally need temporary-home setup/setup and uninstall/uninstall cycles. The second invocation must be `no_op`; unrelated MCP registrations, global-rule bytes outside the managed block, and unrelated Hooks must survive. Corrupt files, duplicate keys, symlinks, concurrent drift, and partial-commit evidence remain required risk cases.

Temporary homes prove only Config-tested behavior. Real host verification must inspect the active `keepygaga` registration and all eight tools. Grok and Hermes should use their official MCP diagnostics when available.

## Hook diagnostics

Built-in Hooks execute through `keepygaga hook run context|route|closeout`. The Codex projection carries the absolute config path as a URL-safe encoded `--config-base64` argument that the Keepygaga CLI decodes; this keeps the config path and its shell-sensitive characters out of the Windows command parser without relying on unsupported Hook-entry environment fields. Codex setup must execute the final projected `SessionStart` command through the target platform's command interpreter, close stdin, and validate the Codex output envelope before writing `hooks.json`; calling the Python module through an argument array is not equivalent verification. This is protocol verification of the projected command, not live-host verification. Verify that projected commands use the installed launcher and resolve the current absolute config path. Context failures return an explicit bootstrap-error payload; they must not silently substitute another memory source. Route state is transient, contains no raw prompt, and expires. Closeout is deduplicated and respects host re-entry signals.

If Hook setup fails, inspect the target host's native event schema, the Keepygaga ownership markers, the stable launcher, and the configured Memory Root. Do not add an external Hook runtime as a fallback.

## Failure routing

- Invalid config or Memory Root: run Doctor, fix the exact live path or malformed page, and retry. Do not initialize over invalid existing content.
- `write_conflict`: reread the returned `latest` snapshot when present and reclassify. A repair conflict returns only the current version; call scoped `list` again and retry only if it still marks the page repairable. Never retry an old version unchanged.
- `capacity_exceeded`: for a fixed page, refine the candidate or ask the user what to remove. For a dynamic page, use scoped list/read and versioned move to reuse a suitable destination or create a bounded new one. A full target scope requires user-led organization; do not loop.
- `repairable=true`: call `update(target=repair)` once with the returned path and version. Conflicts, non-repairable pages, and repair failures require an exact user-facing report rather than guessing.
- `partial_commit`: treat reported components and backups as live evidence, inspect them, then rerun the same idempotent operation.
- Contract marker corruption or duplicate managed blocks: fail closed and repair the exact host rules file manually.
- MCP verification failure: inspect the stable launcher, absolute config path, and returned recovery data.
- Hook bootstrap error: report it; do not guess or use a different retrieval system.
- Upgrade succeeded but repair failed: the package is new while host projection may be old; resolve the reported host error and run `keepygaga repair --yes`.
- Installer subprocess capture always decodes package-manager and host CLI output as UTF-8. Missing stdout/stderr is treated as empty so a Windows locale cannot turn an upgrade or repair failure into `UnicodeDecodeError` or `AttributeError`.

Doctor reports non-sensitive metadata only. `ok` means applicable checks passed, `warning` requires reading the individual check, and `error` blocks setup. Per-scope page counts and page-capacity warnings may be soft; missing legacy Fact dates are valid and produce no warning. Permissions, malformed content, invalid dates, or unwritable paths are blocking.

## Release

Release tags are `v<application-version>`. The tag workflow reruns tests and static checks, builds wheel and sdist, verifies inventory, and creates a GitHub Release containing the two distributions, an immutable all-in-one distribution bundle, and `SHA256SUMS`. The bundle becomes canonical as soon as it is uploaded to the draft: a failed run resumes from that bundle, uploads only missing individual assets, verifies existing assets byte-for-byte, and publishes only after the asset set is internally consistent. Reruns never overwrite or delete existing release assets. Protect the `v*` tag namespace before the first tag. PyPI publishing is not enabled; adding it later requires a trusted publisher and must consume the verified GitHub Release assets without rebuilding them. Never add a publishing token to the repository.
