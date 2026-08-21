# Keepygaga

[English](README.md) | [简体中文](README.zh-CN.md)

**A small, deliberate long-term memory for AI agents.**

AI agents do not get better by remembering everything. If every conversation,
temporary state, and project detail is pushed into long-term memory, useful
facts are buried under stale and irrelevant context. Memory without selection
is noise.

Keepygaga keeps only a small set of durable facts that remain useful across
tasks: who the user is, how they want an Agent to work, and a few ongoing
topics, responsibilities, or relationships. These memories stay in readable
local Markdown, and every change goes through an explicit, versioned MCP tool.
There is no database, index, or embedding service.

For code projects, the priority is not to remember more about the user. The
Agent should instead keep the repository's own terms, architecture, operating
guides, and important decisions organized in `AGENTS.md`, `CONTEXT.md`, and
`docs/`. Keepygaga does not replace project documentation; it supplies only the
small amount of stable personal context that is useful across projects.

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
judged useful across tasks. In code projects, current plans and progress belong
to the repository's own documentation, not the user's personal memory.

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
- [`uv`](https://docs.astral.sh/uv/) is recommended

Obsidian is optional. It is recommended only as a convenient way to browse and
edit the Markdown memories; Keepygaga works with an ordinary filesystem
directory and does not require Obsidian to be installed or running.

## Install

Give the prompt below to the Agent that should use Keepygaga:

```text
Install and connect https://github.com/TimWongUp/keepygaga for yourself.

1. Read the repository `AGENTS.md` and the current host's MCP documentation, then determine whether the Agent actually runs in native Windows, macOS, Linux, or WSL; all subsequent paths and the Python executable must belong to that same runtime.
2. Run `uv sync`, copy `keepygaga.example.toml` to a machine-local `keepygaga.toml`, and resolve `memory.root`: prefer an existing memory tree explicitly supplied by the user in this turn, then a single valid tree from an existing Keepygaga configuration; do not scan an entire disk. If no existing tree is available, choose a new writable directory. If candidates are ambiguous or the user's intent is unclear, ask only for the missing choice.
3. When reusing an existing tree, point `memory.root` directly to it, do not copy, move, or rewrite its pages, and run `uv run keepygaga doctor --json` first. Inspect the JSON check whose `id` is `memory_tree`: run `uv run keepygaga memory init` to fill missing structure only when its message explicitly reports that the tree is not initialized. If it reports `invalid_source`, malformed content, or a specific invalid page, stop the installation and report the exact path to the user; do not run init or continue registration. After init, rerun Doctor regardless of the command exit code or whether the payload says `applied` or `no_op`, and treat the new `memory_tree` check as authoritative. For a new directory, run init to create the canonical tree. `memory init` must never overwrite existing files.
4. Register `mcp_server.py` as a stdio server under the key `keepygaga`, using the virtual environment's native Python and an absolute `KEEPYGAGA_CONFIG`. Preserve unrelated host MCP settings, and do not sync `.venv` or `keepygaga.toml` between machines.
5. Merge `docs/agent-contract.md` into the global host rules that are actually loaded, preserving unrelated settings.
6. If the host supports Hooks, read `docs/hooks/README.md`, select exactly the page for the current Agent host, and install only the capabilities documented on that page. Use the same physical memory root as Keepygaga, merge only Hook entries owned by that runtime, and preserve every unrelated host setting. If no compatible runtime is available, finish the MCP installation and report that Hook integration was not installed; do not invent or download Hook executables.
7. Run `uv run keepygaga doctor --json` and `uv run python scripts/smoke_mcp_server.py`, then confirm the host exposes exactly list, read, create, add, update, move, rename, and delete. When Hooks were installed, also run the selected Agent host's verification.
8. On a first installation only, inspect content that predated this installation in the host's actually loaded global rules and identify candidate long-term personal preferences about how the user wants the Agent to respond and work. Skip this step for reinstalls, repairs, or upgrades, and do not use the Agent Contract or installation instructions merged in this run as candidate sources. Exclude safety boundaries, tool or memory routing, project rules, current state, inference, and facts recoverable from a direct source. Show the user the deduplicated candidates and ask once whether to import them into `preferences.md`; do not write before explicit confirmation. After confirmation, first `read` `preferences.md`, classify each candidate as covered / refines / new / conflict, and write confirmed candidates as `stated`. If the user declines or there are no candidates, write nothing and do not save an onboarding marker.

Report the files changed, memory root, MCP registration, validation results, and remaining gaps. Never print credentials.
```

## Use

```bash
uv run keepygaga doctor
uv run keepygaga memory init
uv run python mcp_server.py
```

`doctor` checks core memory and reports the eight raw tools. `memory init`
creates the canonical Markdown tree and refuses to overwrite existing files.
Running the CLI without a subcommand prints help.

Register the server in your MCP host under the ID `keepygaga`, so the full host
tool names look like `mcp__keepygaga__read`:

```json
{
  "mcpServers": {
    "keepygaga": {
      "command": "/path/to/keepygaga/venv/bin/python",
      "args": ["/path/to/keepygaga/mcp_server.py"],
      "env": {
        "KEEPYGAGA_CONFIG": "/path/to/keepygaga.toml"
      }
    }
  }
}
```

`KEEPYGAGA_CONFIG` overrides the default config path.

## Core capabilities (self-contained)

The MCP server is fully self-contained in this repository. After uv sync,
keepygaga doctor, and the smoke test pass, all eight memory tools are ready
to use. No external runtime or service is required.

## Optional: Hook integration (requires external runtime)

Hook integration is **optional** and requires an external Agent Hook Runtime
that is **not included** in this repository. It can inject the two core
memory pages and routing listing at session start, remind the Agent to route
memory work before each turn when the host supports it, and prompt Project /
Memory Closeout through that host's supported event. The installing Agent must
If you want Hook integration, the installing Agent must select the exact host contract from [`docs/hooks/`](docs/hooks/README.md) and use
a compatible runtime already selected for the target machine; the MCP
server remains fully usable when no Hook runtime is installed.

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
- Applied mutations return a server-generated receipt; echo it exactly once
  and never invent one for reads, no-ops, skips, or failures.

## Acknowledgements

Keepygaga's core memory design was inspired by Claude's memory system.

Thanks also to the Claude team for their pioneering work on AI memory.

## License

[MIT](LICENSE)
