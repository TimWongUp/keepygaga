# Contributing to Keepygaga

Thanks for helping improve Keepygaga. Small, focused contributions are easiest
to review and maintain.

## Before you start

- Search existing issues before opening a new one.
- Open an issue first for changes to memory semantics, public MCP tools, file
  formats, or host integration contracts.
- Never include credentials, private memory pages, or identifying user data in
  issues, tests, logs, or pull requests.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities
  privately according to [SECURITY.md](SECURITY.md).

## Development setup

Keepygaga requires Python 3.12 or newer and uses `uv` for its development
environment:

```bash
git clone https://github.com/TimWongUp/keepygaga.git
cd keepygaga
uv sync
```

The repository's `AGENTS.md` and the relevant documents under `docs/` describe
the current project contracts. Code and tests remain authoritative for exact
runtime behavior.

## Verification

Run the complete local validation before submitting a pull request:

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
uv run python scripts/smoke_mcp_server.py
uv build
```

Add or update tests when behavior changes. Update the relevant contract fixture
or documentation when a public format, MCP schema, or operating procedure
changes.

## Pull requests

- Keep each pull request limited to one purpose.
- Explain the user-visible outcome and list the verification performed.
- Preserve compatibility unless the issue explicitly agrees on a breaking
  change.
- Do not commit local configuration, virtual environments, generated build
  output, credentials, or real memory content.

By submitting a contribution, you agree that it may be distributed under the
project's [MIT License](LICENSE).
