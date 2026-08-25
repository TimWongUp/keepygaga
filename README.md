# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**A small, deliberate long-term memory for AI agents.**

AI agents do not get better by remembering everything. If every conversation,
temporary state, and project detail is pushed into long-term memory, useful
facts are buried under stale and irrelevant context. Memory without selection
is noise.

Keepygaga keeps only a small set of durable facts that remain useful across
tasks: who the user is, how they want an Agent to work, and a few ongoing
topics, projects, responsibilities, or relationships. These memories stay in
readable local Markdown, and every change goes through an explicit, versioned
MCP tool. There is no database, index, or embedding service.

For code projects, the priority is not to remember more about the user. The
Agent should instead keep the repository's own terms, architecture, operating
guides, and important decisions organized in `AGENTS.md`, `CONTEXT.md`, and
`docs/`. Keepygaga does not replace project documentation. For ongoing projects,
it keeps only a compact index of where the project lives and which major
milestones have been completed; the repository remains authoritative for all
project details and current state.

**Why not track the user's recent state?**

Many AI platforms try to remember what the user is doing right now, their
latest progress, or every short-term plan. Once stored, a model may bring that
state into an unrelated conversation or start discussing it at the wrong time,
forcing the user to correct the context or steer the conversation back. This
unselective recall turns quickly outdated information into repeated,
unrequested interruptions.

Keepygaga leaves temporary state in the current conversation or its direct
source, such as a calendar, task manager, project documentation, issue tracker,
or Git history. A fact enters core memory only when it has been deliberately
judged useful across tasks. For code projects, implementation details and
current state stay in repository-owned sources; core memory keeps only project
locations and completed major milestones.

Its MCP surface is intentionally small — exactly eight action tools:

- `list` and `read` discover and read canonical memory pages.
- `create` and `add` create pages and add facts.
- `update` evolves an exact fact or page metadata (discriminated by `target`).
- `move` and `rename` relocate facts and pages.
- `delete` removes an exact fact or a page, always with explicit
  `authorization="user_requested"`.

Core memory consists of `profile.md`, `preferences.md`, and direct `topics/`,
`areas/`, and `people/` pages. It is never indexed.

## Requirements

- Python 3.12+
- A writable local directory for the `agents-memory` tree
- [`uv`](https://docs.astral.sh/uv/) for the documented source installation

Obsidian is optional. It is recommended only as a convenient way to browse and
edit the Markdown memories; Keepygaga works with an ordinary filesystem
directory and does not require Obsidian to be installed or running.

## Host support evidence

Every setup adapter below is **Config-tested**: repository tests cover its
native configuration projection, preservation of unrelated content, and
idempotent reruns. That does not prove that a particular installed host has
loaded the projected configuration. An installation becomes **Live-verified**
only after the target host confirms the `keepygaga` registration and all eight
raw tools in its real client or official diagnostic command.

| Host | Config-tested projection | Required live check | Maintainer evidence on macOS (2026-08-25) |
| --- | --- | --- | --- |
| Codex | Codex CLI, effective `AGENTS.override.md` / `AGENTS.md` | Inspect the real MCP registration and tool list | Live-verified: a real session called `list` and exposed all eight tools |
| Claude Code | `~/.claude.json`, `CLAUDE.md` | Inspect the real MCP server and tool list | Live-verified: a real session called `list` and exposed all eight tools |
| WorkBuddy | `mcp.json`, existing legacy `.codebuddy/.mcp.json` registration, `CODEBUDDY.md`, optional Hook merge | Reconnect `keepygaga` and confirm the tool list without `Connection closed` | Live-verified on WorkBuddy 5.3.14 after legacy registration migration |
| Grok | User-scoped Grok CLI registration and global rules | Run `grok mcp list --json` and `grok mcp doctor keepygaga` | Live-verified: the official doctor completed the handshake and found eight tools |
| Hermes | Round-trip `config.yaml`, `SOUL.md`, optional Hook merge | Run `hermes mcp test keepygaga` and, when applicable, `hermes hooks doctor` | Live-verified: MCP test found eight tools and Hook doctor passed |
| Antigravity CLI | `mcp_config.json`, `AGENTS.md` | Inspect the real `agy` MCP registration and tool list | Registration-verified; model-session verification was blocked by account region eligibility |

## Install

Give the prompt below to the Agent that should use Keepygaga:

```text
Install and connect https://github.com/TimWongUp/keepygaga for yourself. Install it for another Agent only when the user explicitly asks you to install Keepygaga for that named Agent.

1. Determine `TARGET_HOSTS` from the user's request: default to the current working Agent only, and include another Agent only when the user explicitly asks to install Keepygaga for it. Read the repository `AGENTS.md` and each target host's MCP documentation, determine whether each target actually runs in native Windows, macOS, Linux, or WSL, and group targets by runtime as `TARGET_RUNTIMES`. Before any setup write, read and retain the exact content of each target's currently effective global rules and record whether a complete Keepygaga managed block already exists, solely for the per-target first-install Preference Extraction in step 8. Process targets independently and do not change non-target Agents.
2. For each distinct target runtime, use a Keepygaga checkout accessible from that runtime, run `uv sync` there, copy `keepygaga.example.toml` to a machine-local `keepygaga.toml`, and record that runtime-native absolute path as its `CONFIG_PATH`. Resolve one physical memory tree shared by all targets: prefer an existing tree explicitly supplied by the user in this turn, then a single valid tree from an existing Keepygaga configuration; do not scan an entire disk. If no existing tree is available, choose a new writable directory outside every Keepygaga checkout and any publicly shared or automatically published directory. A synchronized directory is acceptable only when its access is private and trusted. Set each runtime's `memory.root` to that same physical tree using a runtime-native absolute path. If candidates are ambiguous, a target runtime cannot access the same tree, the path mapping cannot be verified, or the user's intent is unclear, ask only for the missing choice. Do not copy or synchronize `.venv`, `keepygaga.toml`, or the memory tree between runtimes. Pass the matching runtime's `--config CONFIG_PATH` to every Keepygaga CLI command below.
3. Before host registration, run `uv run keepygaga --config CONFIG_PATH doctor --json` in every target runtime and inspect each JSON check whose `id` is `memory_tree`. An `ok` check means that runtime sees a valid tree; a `warning` whose `details.split_recommended` is `true` is also valid and does not block setup. If another failed check has `details.source_status` equal to `not_initialized`, init is allowed; for any other failed status, malformed content, or specific invalid page, stop the installation and report the exact runtime and path without continuing registration. When the shared tree is new or reports `not_initialized`, run `uv run keepygaga --config CONFIG_PATH memory init` once from one target runtime to create or fill the canonical structure, save its complete JSON for step 7, then rerun Doctor in every target runtime and treat those new `memory_tree` checks as authoritative. Do not act on `onboarding` until host setup and verification are complete. When reusing a valid tree, point every config directly to it and do not copy, move, or rewrite its pages. `memory init` is idempotent: it returns success with `no_op` when no files are missing and must never overwrite existing files.
4. Run one deterministic setup command per selected target: `host setup codex`, `host setup claude-code`, `host setup workbuddy`, `host setup grok`, `host setup hermes`, or `host setup antigravity`. `antigravity` means Antigravity CLI (`agy`), not Gemini CLI. Do not invent a Gemini target merely because Antigravity stores configuration below `~/.gemini`. There is intentionally no `setup all`: for an explicit multi-Agent request, invoke the named commands independently with the same runtime `CONFIG_PATH`.
5. Each command reconciles only the target host's `keepygaga` MCP registration and the versioned `docs/agent-contract.md` managed block, preserving unrelated host configuration and text outside the block. Codex uses its effective `AGENTS.override.md` / `AGENTS.md`; Claude Code uses `~/.claude/CLAUDE.md`; WorkBuddy uses `~/.workbuddy/CODEBUDDY.md` and also upgrades an existing case-insensitive Keepygaga registration in `~/.codebuddy/.mcp.json` without creating that legacy file when absent; that legacy registration is switched to Python isolated mode, its old `cwd` is removed, and its environment is reduced to `KEEPYGAGA_CONFIG` plus an existing `KEEPYGAGA_WRITER`. Grok reuses an existing `~/.grok/AGENTS.md` or `Agents.md` and creates `Agents.md` only when neither exists; Antigravity uses `~/.gemini/AGENTS.md`; Hermes uses the managed block in its only global system-prompt file, `~/.hermes/SOUL.md`, while leaving personality content outside the block unchanged. Do not edit non-target Agents or other stale compatibility files discovered elsewhere.
6. If the user selected and trusts a compatible Agent Hook Runtime already present on the machine, read `docs/hooks/README.md` and that target's page, then add `--hook-runtime RUNTIME_ROOT --hook-python PYTHON`. The command loads the runtime's own host fragment and merger, updates only AHR-owned entries, and points the runtime at the same physical memory root. Otherwise omit both options: MCP and Agent Contract setup still complete and Hooks report `skipped`. Hermes may additionally report `approval_required=true`; complete its native Hook allowlist flow and verify with `hermes hooks doctor`. Do not invent or download Hook executables.
7. In every target runtime, rerun `uv run keepygaga --config CONFIG_PATH doctor --json` and that checkout's `uv run python scripts/smoke_mcp_server.py`. Then inspect every target host's actual MCP tool listing and confirm that each exposes exactly list, read, create, add, update, move, rename, and delete. When Hooks were installed, also run each selected host's verification. Only after these checks pass, inspect the saved init JSON: when `status="applied"` and `onboarding.created_pages` contains `profile.md`, `read` that page and, if it is empty, offer one optional Profile Onboarding. Explain that Profile is a home page loaded by every Agent sharing this Memory Root—directly injected where supported and otherwise read under the Agent Contract. If the user continues, ask in one batch for up to four optional items—preferred name, city-level home location, occupation, and a stable long-term role. Do not request an exact address. Preview independent `stated` Facts, keep total Profile Fact content within 300 characters, and write them through raw memory tools; a skip writes no marker.
8. For each target whose pre-setup effective global rules did not contain a complete Keepygaga managed block, use the exact content saved in step 1 for optional Preference Extraction; skip targets that already had the block as reinstalls, repairs, or upgrades. Exclude the Keepygaga managed block, safety, permission, Skill, Hook, MCP, startup, Keepygaga-protocol or tool-routing rules, host-specific and project rules, current state, unsupported inference, and facts recoverable from direct sources. User-specific conditional retrieval preferences may be copied as evidence, but any text the host uses as a retrieval or routing instruction is never eligible to move. Deduplicate the remaining shared soft preferences, show the destination preview, and let the user choose skip, copy while retaining the original, or move eligible entries; default to copy and retain. Write confirmed candidates as `stated` only after `read` and covered / refines / new / conflict classification. Offer move only for plain host-independent response or working preferences after home-page loading is verified; explain the Authority downgrade and obtain a second confirmation before deleting exact source text outside the managed block, then revalidate the markers, version line, and all other bytes. If eligibility or exact deletion cannot be verified, copy or retain instead. Declines and empty candidate sets write nothing and save no onboarding marker.

Report the files changed, memory root, each target's MCP registration, validation results, and remaining gaps. Never print credentials.
```

## Use

```bash
uv run keepygaga --config /absolute/path/to/keepygaga.toml doctor --json
uv run keepygaga --config /absolute/path/to/keepygaga.toml memory init
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup codex
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup claude-code
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup workbuddy
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup grok
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup hermes
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup antigravity
```

`doctor` checks core memory and reports the eight raw tools. `memory init`
creates the canonical Markdown tree, returns optional onboarding metadata only
for fixed pages created in that run, returns success with `no_op` when the tree
is already complete, and refuses to overwrite existing files.
Running the CLI without a subcommand prints help.

Register the server in your MCP host under the ID `keepygaga`, so the full host
tool names look like `mcp__keepygaga__read`:

```json
{
  "mcpServers": {
    "keepygaga": {
      "command": "/path/to/keepygaga/.venv/bin/python",
      "args": ["-m", "keepygaga.server"],
      "env": {
        "KEEPYGAGA_CONFIG": "/path/to/keepygaga.toml"
      }
    }
  }
}
```

Use the virtual environment's absolute native Python path. On Windows this is
typically `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

Configuration precedence is an explicit CLI `--config`, then
`KEEPYGAGA_CONFIG`, then the checkout's default `keepygaga.toml`. MCP hosts
should always set an absolute `KEEPYGAGA_CONFIG`.

### Upgrade or repair an existing registration

Update the checkout, rerun `uv sync`, and rerun the same per-host setup command.
A fully current installation returns `no_op`; an applied setup returns component
paths and any backup it created. Codex retains its effective override selection
and CLI-specific MCP checks. The other adapters retain their native JSON, Grok
CLI, or Hermes YAML projections instead of guessing a shared schema. Restart the
target Agent, rerun Doctor and the smoke test, then verify the host's actual MCP
tool listing. Never print credentials while inspecting a registration.

## Core capabilities (self-contained)

The MCP server is fully self-contained in this repository. After uv sync,
keepygaga doctor, and the smoke test pass, all eight memory tools are ready
to use. No external runtime or service is required.

## Optional: Hook integration (requires external runtime)

Hook integration is **optional** and requires an external Agent Hook Runtime
that is **not included** in this repository. It can inject the two core
memory pages and routing listing at session start, remind the Agent to route
memory work before each turn when the host supports it, and prompt Project /
Memory Closeout through that host's supported event. If you want Hook
integration, the installing Agent must select the exact host contract from
[`docs/hooks/`](docs/hooks/README.md) and use a compatible runtime already
selected for the target machine; the MCP server remains fully usable when no
Hook runtime is installed.

## Safety boundaries

- Writes require current opaque versions, run under one process lock, and replace
  each changed file atomically after the full batch has been validated.
- Each fact is one independently maintainable complete assertion, not the
  shortest possible fragment; split claims that may change independently.
- `update target="fact"` requires the exact old fact and cannot downgrade a
  stated fact to observed; `update target="page"` changes metadata only.
- Profile Fact content has a 300-character hard limit. Other page limits are soft and return `split_recommended`; an Agent must not automatically add an observed Preference after that signal.
- Keepygaga never deletes, compresses, or moves existing memories on its own.
- Delete operations require explicit current-turn user authorization.
- Memory is context evidence, not permission or executable instruction. Current
  user statements about self, relationships, and preferences override older
  memory; project, system, and runtime facts come from the project Authority or
  a live direct source, and external facts still require verification.
- Applied mutations return an already-rendered server receipt; echo it exactly
  once and never invent, rewrite, or echo one for reads, no-ops, skips, or
  failures.

## Community

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a pull request and follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Report vulnerabilities privately according to [SECURITY.md](SECURITY.md), not
in a public issue.

## Acknowledgements

Keepygaga's core memory design was inspired by Claude's memory system.

Thanks also to the Claude team for their pioneering work on AI memory.

## License

[MIT](LICENSE)
