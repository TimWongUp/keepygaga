# Gemini CLI Hooks

Gemini CLI supports session context injection, per-turn memory routing, and
write-triggered Closeout.

- Live target: `~/.gemini/settings.json`, under `hooks`.
- `SessionStart`: run `context_hook.py gemini SessionStart` with timeout `10000`
  milliseconds.
- `BeforeAgent`: run `memory_route_hook.py gemini BeforeAgent` with timeout
  `2000` milliseconds.
- `AfterTool` with matcher `write_file|replace`: run
  `closeout_hook.py gemini AfterTool` with timeout `2000` milliseconds.

Gemini timeout values are milliseconds. Merge into nested `hooks` lists and
preserve other matchers and commands. Verify one event of each supported type;
do not add subagent, compact, or Stop behavior not listed here.
