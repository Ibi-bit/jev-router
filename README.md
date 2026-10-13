# jev-router

A prompt router for AI coding agents. For each prompt it:

1. Scores the installed skills against the prompt with cheap keyword matching.
2. Asks the Jev decision API to pick one skill and one model from a short list.
3. Switches the model (OpenCode only) and adds the skill's instructions to the prompt.

Every decision is appended to `routing-log.jsonl`.

## Supported harnesses

| Harness | Adapter | Can switch model | Can add skill context | Status |
| --- | --- | --- | --- | --- |
| OpenCode | [`adapters/opencode/index.ts`](adapters/opencode/index.ts) | Yes | Yes (rewrites the prompt) | Loads; per-prompt routing not yet confirmed end to end |
| VS Code (Copilot agent hooks) | [`adapters/vscode/hooks.json`](adapters/vscode/hooks.json) | No | Advisory message only | Hook runs from the CLI; not checked in a live VS Code session |
| Claude Code | [`adapters/claude-code/settings.json`](adapters/claude-code/settings.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Codex CLI | [`adapters/codex/hooks.json`](adapters/codex/hooks.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Gemini CLI | [`adapters/gemini-cli/settings.json`](adapters/gemini-cli/settings.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Cursor | [`adapters/cursor/hooks.json`](adapters/cursor/hooks.json) | No | No (output format not verified) | Hook runs; advisory output only |

Hook-based harnesses only let a hook observe the prompt. They cannot change the model, so for them
the router only suggests a skill and model. Only OpenCode applies the decision.

## Quick start

Requirements: Python 3.9+, and `OPENROUTER_API_KEY` in the environment.

```sh
git clone <this repo> ~/jev-router
export OPENROUTER_API_KEY=...   # set this in your shell profile
python3 ~/jev-router/tests/test_hooks.py     # offline checks
python3 ~/jev-router/router.py "Add a pause screen to the game"
```

Then install the adapter for your harness. See [docs/harnesses.md](docs/harnesses.md).

If `OPENROUTER_API_KEY` is missing or the Jev call fails, the router uses `default_model_key` and
no skill. It never blocks a prompt.

## Layout

```
router.py              routing logic and CLI (also the hook entry point)
config.json            models, skill directories, Jev endpoint
test-skills/           example skills for testing
tests/
  test_hooks.py        offline tests for every harness's hook output
  test_router.py       hook and Jev accuracy on tests/cases.json
  cases.json           labelled prompts
adapters/              per-harness config files and the OpenCode plugin
docs/                  harness setup, configuration, routing behaviour
```

## Cost

Only the models listed in `config.json` can be chosen, and Jev only ever picks from that list.
Each prompt makes one Jev call plus one call to the chosen model. See [docs/configuration.md](docs/configuration.md)
for how to set the model list and spending limits.

## Docs

- [Harness setup](docs/harnesses.md)
- [Configuration](docs/configuration.md)
- [How routing works](docs/routing.md)
