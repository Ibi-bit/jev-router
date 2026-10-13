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

## Example training run (on WormsDestruction)

1. **Scan skills**
   ```sh
   python3 skills/train-router/scripts/scan_skills.py ~/WormsDestruction --out data/skills.json
   ```

2. **Generate data** (this was run once to produce all examples below)
   ```sh
   python3 skills/train-router/scripts/make_dataset.py data/skills.json --out data/ --per-skill 25 --negatives 40 --max-calls 30
   ```
   → `train.jsonl` (685 examples), `valid.jsonl` (76 examples), 29 API calls, ~36k tokens.

3. **Train** with reduced settings to fit in 8 GB RAM
   ```sh
   .venv/bin/python skills/train-router/scripts/train.py \
     --data data/ \
     --adapter adapters/router \
     --iters 100 \
     --layers 4 \
     --batch-size 1
   ```
   Saved adapter: `adapters/router/0000100_adapters.safetensors` (≈5 MB).

4. **Evaluate**
   ```sh
   .venv/bin/python skills/train-router/scripts/evaluate.py \
     --data data/ \
     --adapter adapters/router \
     --base mlx-community/Qwen2.5-1.5B-Instruct-4bit
   ```
   Accuracy: **51.3%** (39/76 correct on the validation set).

## Typical results

| Label type | Count correct / total |
| --- | --- |
| skills that match intent | 25 / 35 |
| skills that match literal keywords | 14 / 30 |
| `none` (no skill fits) | 0 / 11 |

Accuracy on generated data is optimistic (labels came from a model). Check against real prompts: see
`tests/cases.json` and `routing-log.jsonl`.

Adding or renaming a skill changes the label set; regenerate the data and retrain.

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