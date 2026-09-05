# Keepygaga Operations

## Installation and operations control plane

The `keepygaga` CLI installs and maintains the product; it is not the routine interface for browsing or editing memory. Users inspect, correct, and organize the shared Memory Root in Obsidian or another Markdown editor, while Agents use MCP and Hooks.

The recommended entry is the [Agent Fast Install To-do](agent-install.md). It checks the launcher and installed version first, selects exactly one lifecycle branch, and touches only the current host. Existing valid configuration and memory bypass initialization. The separate [Home Page source migration](source-migration.md) is loaded only for first initialization or a concrete duplicate; its complete host inventory and user-confirmed source choice do not burden routine updates or no-op checks.

Download `keepygaga-X.Y.Z-py3-none-any.whl` and `SHA256SUMS` from the same latest GitHub Release to private, non-symlinked paths. Rehash the exact wheel immediately before installing that same absolute path with `uv tool install /absolute/private/path/keepygaga-X.Y.Z-py3-none-any.whl`, then run `uv tool update-shell`. SHA-256 detects corruption or asset mismatch; it is not a signature, provenance proof, publisher authentication, or verification of dependencies resolved from the package index. Restart the terminal so the tool directory is on `PATH`, then run `keepygaga install`. Interactive installation prompts for the Memory Root before host selection. An existing configured root is reused automatically when adding another host. Non-interactive first installation requires `--yes`, one or more explicit `--host` values, and an explicit `--memory-root` only when reusing a private, trusted tree.

- `keepygaga status` reads live config and Doctor, reports the running and recorded versions and channels, compares the live Contract and MCP/Hook wiring against setup preflight, and labels host checks that still require live verification. Wiring inspection does not apply plans or run Hook smoke; Codex and Grok use their read-only MCP diagnostic commands. `keepygaga status --latest-version TAG --host HOST` additionally returns one read-only `lifecycle.action`: `update`, `initialize`, `activate`, `repair`, `no_op`, or `manual_review`. The Agent classifies a missing launcher as the separate `install` action.
- `keepygaga repair --yes` reruns idempotent desired-state reconciliation for recorded hosts, including removal of obsolete Keepygaga-owned Hook entries.
- `keepygaga uninstall --yes` removes recorded host wiring while preserving config and memory.
- `keepygaga host setup|uninstall HOST` remains the deterministic expert path.

Install state is discovery evidence only. If it disagrees with a host's live configuration, the host file and official diagnostic win.

The optional `[memory.limits]` table controls fixed-page characters, dynamic-page characters, and the `topics`, `areas`, and `people` page counts. New installations write the current defaults with adjustment comments; repair and upgrade preserve existing configuration bytes. The Store reloads these limits on every MCP call. Doctor and status report both effective values and whether they came from built-in defaults or the live configuration path. Invalid, unknown, non-integer, or non-positive values fail with the exact `memory.limits` field instead of falling back silently.

To update through the current GitHub Release channel, download the newer wheel and matching `SHA256SUMS`, rehash the exact absolute wheel path, set `UV_TOOL_DIR` to the `lifecycle.tool_root` returned by planned `status` for that command, run `uv tool install --force /absolute/private/path/keepygaga-X.Y.Z-py3-none-any.whl`, then run `keepygaga install --yes --host HOST` to reconcile only the current host. `keepygaga upgrade --yes` remains the explicit all-recorded-host path for a verified `uv-tool` installation and binds `uv` to the active tool root; it is not the update path for a versioned GitHub Release wheel. `pipx`, unknown, and state-mismatched owners fail closed for manual owner-correct replacement instead of being routed through `uv`.

### Project-index migration

`repair` never rewrites Memory Root. Before the next project-memory write under the current Agent Contract, use scoped `list(scope=areas)` and `read` to inventory every legacy project page and identify each project's current Authority from the project itself. Then converge as follows:

A complete Fact follows Contract 7: a brief, canonical Authority, and latest verified integrated outcome and release status when available. For each project being updated, verify the canonical remote primary branch and whether a published Release points to a tag commit containing the outcome; do not infer publication from release-note wording or matching version numbers. If verification is unavailable, preserve the existing Fact and leave that project pending rather than claim its progress is current.

1. If one legacy page already contains one complete Fact per project, rename it to `areas/projects.md`.
2. If no legacy project page exists, create `areas/projects.md` together with its first complete project Fact.
3. If several pages or several Facts describe the same project, compose one complete Fact per project in `areas/projects.md`, then ask the user for explicit current-turn authorization before deleting superseded Facts or pages.
4. Finish only when each maintained project occurs once in the canonical page and no conflicting legacy project record remains.

Existing Contract 4–6 indexes that already have one Fact per project need no structural migration. On the next relevant project-memory update, verify that project against the Contract 7 evidence rules and refine its Fact in place; do not automatically rewrite every project when upgrading the runtime.

Do not create a second canonical index to bypass a conflict, and do not treat `repair` success as migration evidence.

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

Built-in Hooks execute through `keepygaga hook run context|route`. The Codex projection carries the absolute config path as a URL-safe encoded `--config-base64` argument that the Keepygaga CLI decodes; this keeps the config path and its shell-sensitive characters out of the Windows command parser without relying on unsupported Hook-entry environment fields. Codex setup must execute the final projected `SessionStart` command through the target platform's command interpreter, close stdin, and validate the Codex output envelope before writing `hooks.json`; calling the Python module through an argument array is not equivalent verification. This is protocol verification of the projected command, not live-host verification. Verify that projected commands use the installed launcher and resolve the current absolute config path. Context failures return an explicit bootstrap-error payload; they must not silently substitute another memory source. Route reminders are stateless and do not read or write session files. Completion checks are part of the per-turn reminder; Keepygaga registers no PostToolUse or Stop reminder. Hermes and Antigravity combine bootstrap and routing in a single invocation.

The `0.9.0` Hook migration removes `hook run closeout`. Upgrade and reconcile the selected hosts together so their old PostToolUse registrations are removed before normal use resumes. Setup still recognizes old owned closeout and route commands, removes obsolete projections, and preserves unrelated Hooks. Existing temporary Hook-state files are no longer used; no migration or cleanup is required.

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

Apply the [application version policy](architecture.md#application-version-policy) before preparing a release or updating installed hosts:

1. Compare all unreleased product changes with the latest published Release and confirm the reserved version has the required increment. Change only `APPLICATION_VERSION` for the application number and refresh `uv.lock` with `uv lock`; independently change a contract/schema version only when its own compatibility boundary changed.
2. Complete the relevant validation and PR review, then merge the release candidate through the normal branch workflow. A merge or a version edit does not publish anything.
3. With explicit release authorization, create the matching tag on the verified commit and wait for the tag workflow to publish the canonical assets successfully. Never move an existing release tag or replace its assets with a different build. A correction to published product code needs a new version.
4. Update daily-use hosts from that Release's wheel and matching `SHA256SUMS`, through the detected installation owner, then reconcile the requested hosts and verify their configuration and protocol. Report the installed Release version and any host reload still required.

If requested changes are merged but not released, report that they are unreleased and complete any already-authorized release preparation. Obtain release authorization only when it is missing; do not substitute a local wheel or mutable `main` build for the daily-use installation. Contributor checks run in the repository `.venv` and report the source commit plus its unreleased status. A local build's version string alone must never be presented as proof that it is an official Release.

Release tags are `v<application-version>`. The tag workflow reruns tests and static checks, builds wheel and sdist, verifies inventory, and creates a GitHub Release containing the two distributions, a workflow-canonical all-in-one distribution bundle, and `SHA256SUMS`. The bundle becomes canonical as soon as it is uploaded to the draft: a failed run resumes from that bundle, uploads only missing individual assets, verifies existing assets byte-for-byte, and publishes only after the asset set is internally consistent. Workflow reruns never overwrite or delete existing release assets; this policy is not GitHub immutable-release enforcement or cryptographic provenance. Protect the `v*` tag namespace before the first tag. PyPI publishing is not enabled; adding it later requires a trusted publisher and must consume the verified GitHub Release assets without rebuilding them. Never add a publishing token to the repository.
