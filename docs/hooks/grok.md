# Grok Hooks

Grok loads core memory and routing through global rules rather than runtime
context or per-turn Hooks. Only guarded Closeout is installed.

- Live target: `~/.grok/hooks/agent-hook-runtime.json`, under `hooks`.
- `Stop`: run `closeout_hook.py grok Stop` with a 2-second timeout.

The runtime must return the fixed Closeout reminder on the first Stop and no
output when the payload reports `stopHookActive=true`, preventing recursive Stop
handling. Do not install context, per-turn routing, tool-after, or legacy safety
Hooks for Grok. Verify both the first Stop and guarded re-entry.
