# Hermes Hooks

Hermes supports context injection and memory routing before each model call,
then Closeout during verification.

- Live target: `~/.hermes/config.yaml`, under `hooks`; encode commands as YAML
  nodes after rendering native absolute paths.
- `pre_llm_call`: run `context_hook.py hermes pre_llm_call` with a 10-second
  timeout.
- The same `pre_llm_call`: run
  `memory_route_hook.py hermes pre_llm_call` with a 2-second timeout.
- `pre_verify`: run `closeout_hook.py hermes pre_verify` with a 2-second timeout.

Preserve unrelated YAML keys and Hook entries. Verify both pre-model commands
reach the model context and that `pre_verify` emits Closeout at most once for an
unchanged pending state.
