---
name: train-router
description: Train a local LoRA model to pick the right skill for a prompt. Scans every skill in a project, generates labelled prompts with a cheap model, trains an adapter with mlx-lm on this Mac, and reports accuracy. Use when the user wants to train, retrain, or evaluate the jev-router skill picker, or to replace the Jev API call with a local model.
---

# Train the router

Trains a small model that maps a prompt to one skill name (or `none`). It runs in four steps.
Each step is a script in `scripts/`. Run them from `~/jev-router`.

## Costs

- Dataset generation calls a cheap OpenRouter model. Each call is one request for about 25 prompts.
  The default `--max-calls` of 30 covers a project of about 28 skills. Expect a few cents.
- Training and evaluation run locally on the Mac. They cost nothing in API calls.
- Training uses the CPU and GPU for a while and can take tens of minutes. Keep the machine plugged in.

Set a spending limit on the OpenRouter key before running step 2.

## Steps

1. **Scan skills.** Lists every skill the router can see for a project.

   ```sh
   python3 skills/train-router/scripts/scan_skills.py ~/WormsDestruction --out data/skills.json
   ```

2. **Generate data.** Asks the dataset model for prompts that each skill should handle, plus prompts that
   no skill should handle. Writes `train.jsonl` and `valid.jsonl` in mlx chat format.

   ```sh
   python3 skills/train-router/scripts/make_dataset.py data/skills.json --out data/ --per-skill 25 --negatives 40 --max-calls 30
   ```

3. **Train.** Trains a LoRA adapter on the base model with `mlx_lm lora`.

   ```sh
   python3 skills/train-router/scripts/train.py --data data/ --adapter adapters/router
   ```

4. **Evaluate.** Reports exact-match accuracy on `valid.jsonl` and lists the first misses.

   ```sh
   python3 skills/train-router/scripts/evaluate.py --data data/ --adapter adapters/router
   ```

## Before you start

- The project venv must exist: `python3 -m venv .venv && .venv/bin/pip install mlx-lm`.
- `OPENROUTER_API_KEY` must be set for step 2.
- The labels come from the generated data, not from a human. Read a sample of `train.jsonl` before trusting
  the model. Prompts that the dataset model wrote badly teach the router the wrong thing.

## Rules

- Generated prompts that duplicate each other are removed. The split is fixed (every tenth example is
  validation), so results are reproducible for the same data.
- Adding or renaming a skill changes the label set. Regenerate the data and retrain. An old adapter
  does not know the new skill.
- Accuracy on generated data is optimistic. Use `tests/cases.json` and real prompts from
  `routing-log.jsonl` before relying on the adapter.

## Serving the adapter

After evaluation, serve the adapter with the mlx-lm server and point the router at it. The router only calls it
when `decider.type` in `config.json` is `local`:

```sh
.venv/bin/python -m mlx_lm server --model mlx-community/Qwen2.5-1.5B-Instruct-4bit --adapter-path adapters/router --port 8080
```
