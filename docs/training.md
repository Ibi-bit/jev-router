# Training a local skill router

The `train-router` skill (`skills/train-router/`) trains a small LoRA adapter that maps a prompt to a
skill name. The router can then use it instead of the Jev API. Everything except data generation runs
on your Mac, at no API cost.

## Pipeline

| Step | Script | Output | Cost |
| --- | --- | --- | --- |
| 1. Scan skills | `scripts/scan_skills.py <project>` | `skills.json` | none |
| 2. Generate data | `scripts/make_dataset.py skills.json --out data/` | `train.jsonl`, `valid.jsonl` | API calls to `dataset_model` |
| 3. Train | `scripts/train.py --data data/ --adapter adapters/router` | LoRA adapter | local compute |
| 4. Evaluate | `scripts/evaluate.py --data data/ --adapter adapters/router` | accuracy and misses | local compute |

Data is written in the chat format `mlx_lm` expects. Each example has three messages:

1. `system`: the skill catalogue (`Available skills:` plus one line per skill, then the answer rule).
2. `user`: the prompt.
3. `assistant`: the correct skill name, or `none`.

`make_dataset.py` asks `dataset_model` for prompts that each skill should handle, plus prompts that no
skill should handle. Duplicate prompts are removed. Every tenth example goes to `valid.jsonl`.

## Setup

```sh
cd ~/jev-router
python3 -m venv .venv
.venv/bin/pip install mlx-lm
```

Needs Apple Silicon. The default base model, `mlx-community/Qwen2.5-1.5B-Instruct-4bit`, fits in 8 GB of
RAM. Training is slow on a machine that is also doing other work.

## Serving the trained adapter

```sh
.venv/bin/python -m mlx_lm server --model mlx-community/Qwen2.5-1.5B-Instruct-4bit \
  --adapter-path adapters/router --port 8080
```

Then in `config.json`:

```json
"decider": {
  "type": "local",
  "url": "http://127.0.0.1:8080/v1/chat/completions",
  "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
  "model_key": "fast",
  "timeout_s": 10
}
```

The local decider picks only the skill. The model comes from `model_key`, or `default_model_key`
if it is not set. If the server is down or returns an unknown skill name, the router falls back
to the default model with no skill, the same as the Jev path.

## Caveats

- **The adapter knows one skill set.** Its catalogue is baked into training. Adding, removing or
  renaming a skill means regenerating the data and retraining. Using the adapter in a project with
  different skills gives wrong answers.
- **Labels are generated.** A cheap model wrote the prompts and their labels. Read a sample of
  `train.jsonl` before trusting the adapter.
- **Accuracy on generated data is optimistic.** Check against `tests/cases.json` and real prompts from
  `routing-log.jsonl`.
- **Cloudflare is not a training service.** Workers AI serves LoRA adapters that you train elsewhere,
  and only for a fixed list of older base models. It is free only during open beta. The local MLX
  route avoids both limits.

## Cost

- Data generation: about 29 calls for 28 skills, about 36,000 tokens in the first run. Check the price
  of `dataset_model` on OpenRouter. The API calls are the only cost.
- Training and evaluation: nothing beyond electricity and time.
- Set the OpenRouter spending limit before generating data.
