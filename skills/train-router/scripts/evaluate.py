#!/usr/bin/env python3
"""Measure exact-match accuracy of a trained adapter on valid.jsonl.

  python3 evaluate.py --data data/ --adapter adapters/router [--base <model>]
"""
import argparse
import json
import sys
from pathlib import Path

from mlx_lm import generate, load

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import DEFAULT_BASE  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()

    model, tokenizer = load(args.base, adapter_path=args.adapter)
    rows = [json.loads(line) for line in (Path(args.data) / "valid.jsonl").read_text().splitlines()]

    correct = 0
    misses = []
    for row in rows:
        messages = row["messages"]
        prompt = tokenizer.apply_chat_template(messages[:2], add_generation_prompt=True, tokenize=False)
        answer = generate(model, tokenizer, prompt=prompt, max_tokens=12, verbose=False).strip()
        expected = messages[2]["content"]
        if answer == expected:
            correct += 1
        else:
            misses.append((messages[1]["content"], expected, answer))

    print(f"accuracy {correct}/{len(rows)} = {correct / max(len(rows), 1):.1%}")
    for prompt, expected, got in misses[:15]:
        print(f"  expected {expected!r:<28} got {got!r:<28} {prompt[:70]}")


if __name__ == "__main__":
    main()
