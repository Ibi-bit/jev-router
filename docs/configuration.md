# Configuration

Settings live in `config.json` next to `router.py`.

| Key | Meaning |
| --- | --- |
| `models` | Map of model keys to `{id, description}`. Jev picks one key per prompt. The `id` is the `provider/model` string OpenCode switches to. |
| `default_model_key` | Model key used when Jev fails or the API key is missing. |
| `skill_dirs` | Directories scanned for skills, for the CLI (`~` is expanded). |
| `hook_skill_dirs` | Project-relative directories scanned by hooks, relative to the prompt's `cwd`. |
| `hook_top_k` | How many keyword candidates Jev is asked to choose from. |
| `jev.url` | Jev decision endpoint. |
| `jev.model` | Jev model name. |
| `jev.timeout_s` | Seconds to wait for Jev before falling back. |
| `decider` | Who picks the skill. `{"type": "jev"}` (default) uses the Jev API. `{"type": "local", "url", "model", "model_key", "timeout_s"}` uses a trained adapter served by mlx-lm. See [training.md](training.md). |
| `dataset_model` | OpenRouter model used by `train-router` to generate training prompts. |

## Models

Only keys in `models` can be chosen. Each `id` must exist in the OpenCode model catalog, or OpenCode
cannot switch to it. Keep the list short. Jev is shown every model in the list on every prompt, so the
list affects both cost and decision quality.

The router is currently set up to avoid expensive models. `code` and `deep` point at the cheapest
model, so Jev cannot choose a more expensive one. The cheap and free options listed in `config.json`
are there for simple single-step prompts.

## Spending limits

The router does not enforce a budget. Set a monthly spending limit on the OpenRouter key, or top up
with only the amount you are willing to spend. The OpenRouter limit stops charges even if the router
or a harness misbehaves.

Jev's own calls also cost money. Check the price of `jev.model` on OpenRouter.

## Environment

| Variable | Use |
| --- | --- |
| `OPENROUTER_API_KEY` | Required for Jev calls. Without it, every prompt uses `default_model_key`. |
| `JEV_ROUTER` | OpenCode plugin only: path to `router.py` if it isn't `~/jev-router/router.py`. |
