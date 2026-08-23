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

## Install

Give the prompt below to the Agent that should use Keepygaga:

```text
Install and connect https://github.com/TimWongUp/keepygaga for yourself. Install it for another Agent only when the user explicitly asks you to install Keepygaga for that named Agent.

1. Determine `TARGET_HOSTS` from the user's request: default to the current working Agent only, and include another Agent only when the user explicitly asks to install Keepygaga for it. Read the repository `AGENTS.md` and each target host's MCP documentation, determine whether each target actually runs in native Windows, macOS, Linux, or WSL, and group targets by runtime as `TARGET_RUNTIMES`. Process targets independently and do not change non-target Agents.
2. For each distinct target runtime, use a Keepygaga checkout accessible from that runtime, run `uv sync` there, copy `keepygaga.example.toml` to a machine-local `keepygaga.toml`, and record that runtime-native absolute path as its `CONFIG_PATH`. Resolve one physical memory tree shared by all targets: prefer an existing tree explicitly supplied by the user in this turn, then a single valid tree from an existing Keepygaga configuration; do not scan an entire disk. If no existing tree is available, choose a new writable directory outside every Keepygaga checkout and any publicly shared or automatically published directory. A synchronized directory is acceptable only when its access is private and trusted. Set each runtime's `memory.root` to that same physical tree using a runtime-native absolute path. If candidates are ambiguous, a target runtime cannot access the same tree, the path mapping cannot be verified, or the user's intent is unclear, ask only for the missing choice. Do not copy or synchronize `.venv`, `keepygaga.toml`, or the memory tree between runtimes. Pass the matching runtime's `--config CONFIG_PATH` to every Keepygaga CLI command below.
3. Before host registration, run `uv run keepygaga --config CONFIG_PATH doctor --json` in every target runtime and inspect each JSON check whose `id` is `memory_tree`. An `ok` check means that runtime sees a valid tree; a `warning` whose `details.split_recommended` is `true` is also valid and does not block setup. If another failed check has `details.source_status` equal to `not_initialized`, init is allowed; for any other failed status, malformed content, or specific invalid page, stop the installation and report the exact runtime and path without continuing registration. When the shared tree is new or reports `not_initialized`, run `uv run keepygaga --config CONFIG_PATH memory init` once from one target runtime to create or fill the canonical structure, then rerun Doctor in every target runtime and treat those new `memory_tree` checks as authoritative. When reusing a valid tree, point every config directly to it and do not copy, move, or rewrite its pages. `memory init` is idempotent: it returns success with `no_op` when no files are missing and must never overwrite existing files.
4. For a Codex target, run `uv run keepygaga --config CONFIG_PATH host setup codex`. This command uses Codex's own CLI to reconcile only the `keepygaga` MCP registration and installs the versioned `docs/agent-contract.md` managed block into the effective global `AGENTS.override.md` or `AGENTS.md` entry. A non-empty override wins; an empty override falls back to `AGENTS.md`; a managed block in the non-effective candidate stops setup as stale. Do not hand-edit either projection. If the user selected and trusts a compatible Agent Hook Runtime already present on this machine, add `--hook-runtime RUNTIME_ROOT --hook-python PYTHON`; the command then delegates Hook ownership and merge semantics to that runtime. Otherwise omit both options and report that optional Hook integration was skipped. For a non-Codex target, inspect any existing MCP registration under the key `keepygaga`, then register or replace only that entry with `keepygaga.server` as a stdio server, using that target runtime's virtual-environment Python with arguments `-m` and `keepygaga.server`, plus an absolute `KEEPYGAGA_CONFIG` equal to that runtime's `CONFIG_PATH`.
5. For non-Codex targets only, merge `docs/agent-contract.md` into the global rules that host actually loads, preserving unrelated settings. Codex setup owns only the exact block delimited by `KEEPYGAGA:START` and `KEEPYGAGA:END`, records the release version without a content hash, and preserves all bytes outside the block. Do not edit any non-target Agent's global rules.
6. For a non-Codex target that supports Hooks, read `docs/hooks/README.md`, select exactly that host's page, and install only the capabilities documented there. Use the same physical memory root as Keepygaga, merge only Hook entries owned by that runtime, preserve every unrelated host setting, and do not edit Hooks for non-target Agents. If no compatible runtime is available for a target, finish its MCP installation and report that Hook integration was not installed; do not invent or download Hook executables.
7. In every target runtime, rerun `uv run keepygaga --config CONFIG_PATH doctor --json` and that checkout's `uv run python scripts/smoke_mcp_server.py`. Then inspect every target host's actual MCP tool listing and confirm that each exposes exactly list, read, create, add, update, move, rename, and delete. When Hooks were installed, also run each selected host's verification.
8. On a first installation only, inspect content that predated this installation in each target host's actually loaded global rules and identify candidate long-term personal preferences about how the user wants the Agent to respond and work. Skip this step for reinstalls, repairs, or upgrades, and do not use the Agent Contract or installation instructions merged in this run as candidate sources. Exclude safety boundaries, tool or memory routing, project rules, current state, inference, and facts recoverable from a direct source. Deduplicate candidates across all targets, show them to the user, and ask once whether to import them into `preferences.md`; do not write before explicit confirmation. After confirmation, first `read` `preferences.md`, classify each candidate as covered / refines / new / conflict, and write confirmed candidates as `stated`. If the user declines or there are no candidates, write nothing and do not save an onboarding marker.

Report the files changed, memory root, each target's MCP registration, validation results, and remaining gaps. Never print credentials.
```

## Use

```bash
uv run keepygaga --config /absolute/path/to/keepygaga.toml doctor --json
uv run keepygaga --config /absolute/path/to/keepygaga.toml memory init
uv run keepygaga --config /absolute/path/to/keepygaga.toml host setup codex
```

`doctor` checks core memory and reports the eight raw tools. `memory init`
creates the canonical Markdown tree, returns success with `no_op` when the tree
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

Update the checkout, rerun `uv sync`, and rerun the same setup command. For
Codex, `host setup codex` updates the managed Agent Contract block by release
version, reconciles the `keepygaga` MCP transport, and refreshes selected Agent
Hook Runtime entries; a fully current installation returns `no_op`. A non-empty
`AGENTS.override.md` is the effective rules entry; an empty override falls back
to `AGENTS.md`. If the non-effective candidate contains a Keepygaga managed
block, setup stops for the stale/duplicate entry. Rules are read as original
UTF-8 bytes and their outside bytes are preserved; apply order is MCP, rules,
then optional hooks, so a failed MCP apply does not write rules. Other MCP
environment variables are preserved; setup stops for custom fields that the CLI
cannot preserve losslessly. Then restart Codex and rerun Doctor and the smoke
test. For other hosts, inspect and repair the existing registration using their
current host contract while preserving unrelated configuration.

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
- Capacity limits are soft: writes succeed and return `split_recommended`.
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
