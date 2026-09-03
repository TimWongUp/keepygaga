# Agent Install To-do

Use this procedure when a user gives an Agent the recommended one-sentence Keepygaga installation request. Complete one current host at a time. The installation is complete only when the selected release is verified, the current host is activated, every durable Profile or Preference meaning has one injection source, and the achieved verification level is reported.

## 1. Establish the current state

- [ ] Identify the current operating system, architecture, shell, and Agent host. Ask the user to name the host only when live evidence is ambiguous.
- [ ] Target only the Agent running this task. Detected sibling hosts are context, not installation targets.
- [ ] Locate the current host's effective global rules entry using the host's current official behavior and the matching Keepygaga adapter. Read it before host activation changes it.
- [ ] Preserve the original global-rules bytes and a digest for concurrency checks. Reject malformed or ambiguous Keepygaga ownership markers.
- [ ] Check for an installed `keepygaga` launcher, its installation channel and version, the live Keepygaga config, and any recorded hosts.
- [ ] Resolve the configured Memory Root. Reuse a valid existing root; when no root is configured, propose the platform default or a private user-selected directory. Never place memory in a public or automatically published tree.
- [ ] Inspect existing `profile.md` and `preferences.md` when they exist. Existing valid Home Pages are user data and must not be overwritten.

This step is complete when the target host, release path, effective rules entry, config path, Memory Root, and every existing-data conflict are known before the first write.

## 2. Prepare the Home Page Source Choice

Extract candidate meanings from the effective global rules before installing the managed Keepygaga Contract:

- **Profile candidates** are identity, background, profession, location, and long-lived roles that should still hold in three months.
- **Preference candidates** are durable response, workflow, formatting, toolchain, and conditional retrieval preferences.

Exclude generic safety rules, host protocols, tool routing, project instructions, current task state, secrets, complete sensitive identifiers, and the Keepygaga managed block. Do not inspect conversation history or host-native memory as a substitute source.

Compare each candidate with the live Home Page and classify it as covered, refines, new, or conflict. Show the user a concise before/after table containing:

| Meaning | Current source | Keepygaga result | Global-rules result |
| --- | --- | --- | --- |
| Exact candidate meaning | Effective rules or Home Page | Add, update, delete, or unchanged | Exact removal or unchanged |

Ask the user to choose exactly one owner for every candidate meaning:

1. **Keepygaga owns it** — write the confirmed meaning to the matching Home Page and remove its exact source statement from the effective global rules.
2. **Global rules own it** — leave the global statement unchanged and do not retain the same meaning in a Keepygaga Home Page.

User confirmation turns the approved candidate into a current explicit statement, so write it with `stated` basis. A mixed paragraph or ambiguous semantic overlap cannot be removed exactly; keep it in global rules or ask the user to split or rewrite it before continuing.

When the effective global rules do not contain enough durable identity or working-preference context to make the Home Pages useful, ask only for the missing information after presenting the extracted candidates. Treat each answer as a new candidate, show its destination, and obtain confirmation before writing it. Do not duplicate an answer into global rules.

This step is complete when every candidate has one selected owner and the user has approved the exact writes and removals. No source changes occur while a candidate remains undecided or conflicted.

## 3. Install the released runtime

- [ ] Open the latest official GitHub Release and select its versioned `keepygaga-X.Y.Z-py3-none-any.whl` asset.
- [ ] Download `SHA256SUMS` from the same Release and verify the wheel before executing it. Stop on a missing or mismatched checksum.
- [ ] For a clean installation, install the verified wheel with `uv tool install ./keepygaga-X.Y.Z-py3-none-any.whl`, then run `uv tool update-shell` when the launcher directory is not already active.
- [ ] For an existing installation, respect its package-manager owner. A GitHub Release wheel installed through `uv tool` is replaced with `uv tool install --force ./keepygaga-X.Y.Z-py3-none-any.whl`; do not make a source checkout the runtime.
- [ ] Run `keepygaga install --yes --host HOST` for the current host only. On a first install that reuses an existing private tree, also pass `--memory-root PATH`.
- [ ] Treat `partial_commit` as live state: inspect the reported components and backups, resolve the stated cause, and rerun only the same idempotent target.

The installer owns config creation, the empty `profile.md` and `preferences.md`, the three dynamic directories, MCP registration, the managed Agent Contract, Keepygaga-owned Hooks, and observational install state. It preserves existing Home Pages and unrelated host configuration.

This step is complete when the stable `keepygaga` and `keepygaga-mcp` launchers resolve and the installer reports `applied` or `no_op` for the current host without an unresolved partial commit.

## 4. Apply the approved source switch

Reload or restart the current host when required so the newly registered Keepygaga MCP tools are available. If the current session cannot reload them, pause with the exact continuation step instead of editing Home Pages as unversioned raw files.

For each approved candidate:

- [ ] Read the latest matching Home Page Snapshot and reclassify the candidate.
- [ ] Re-read the effective global rules and confirm their bytes still match the approved precondition.
- [ ] For Keepygaga-owned meanings, stage both desired results, remove only the exact approved global source statement, and then use `add` for an independent new Fact or `update` for a refinement.
- [ ] For global-owned meanings, leave the global statement in place and remove any matching Home Page Fact only with explicit current-turn user authorization through exact, versioned `delete`.
- [ ] Preserve all unrelated global-rules bytes and the complete Keepygaga managed block.

Cross-source writes are not globally atomic. Recheck both preconditions immediately before applying the staged results. Remove the exact global source first, then perform the versioned Home Page mutation so no durable intermediate state contains both sources. If the Home Page mutation fails, restore the exact global source while the post-removal bytes still prove ownership. If safe restoration is no longer possible, report `partial_commit` with both live sources and the exact recovery action. Never call a missing or duplicated final state successful.

Re-read both injection sources after application. This step is complete only when every approved meaning exists in exactly one source and unrelated global rules and Home Page Facts remain unchanged.

## 5. Leave host-native memory to the user

Keep the host's native memory configuration unchanged. Identify the installed host and version, then find the current official vendor documentation for its memory controls. Give the user:

- the direct official documentation link;
- the exact settings or configuration entry documented for that version;
- the effect of disabling it and the documented recovery path; and
- any unsupported or unverified limitation.

The user performs this optional configuration. Providing instructions is not evidence that native memory was disabled, and the installation report must not claim otherwise.

## 6. Verify and report

- [ ] Run `keepygaga status` and `keepygaga doctor --json`.
- [ ] Verify the current host's MCP registration, managed Contract, Keepygaga-owned Hooks, config path, and Memory Root while preserving sibling entries.
- [ ] Complete a bounded MCP initialize and confirm the exact eight-tool surface for `protocol_verified` evidence.
- [ ] After a real host reload, confirm that the host exposes those tools and receives the expected bootstrap for `live_verified` evidence. Otherwise report `config_verified`, `protocol_verified`, `degraded`, or `unverified` precisely.
- [ ] Confirm that no approved Profile or Preference meaning is injected from both a Home Page and the effective global rules.

Report the installed version and channel, current host, config path, Memory Root, created versus preserved Home Pages, each source choice, verification level, retained data, native-memory documentation supplied, unresolved work, and recovery commands. Do not report success while a checksum, conflict, duplicate injection, partial commit, or required reload remains unresolved.
