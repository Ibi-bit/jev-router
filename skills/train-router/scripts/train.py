#!/usr/bin/env python3
"""Train a LoRA adapter for the router with mlx-lm (runs locally, no API cost).

  python3 train.py --data data/ --adapter adapters/router [--iters 600]

Needs the project venv: python3 -m venv .venv && .venv/bin/pip install mlx-lm
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROUTER_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="directory with train.jsonl and valid.jsonl")
    parser.add_argument("--adapter", required=True, help="where to save the adapter")
    parser.add_argument("--base", default=DEFAULT_BASE, help="base model (mlx-community repo or local path)")
    parser.add_argument("--iters", type=int, default=600)
    parser.add_argument("--layers", type=int, default=8, help="how many top layers get LoRA weights")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    args = parser.parse_args()

    python = ROUTER_ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        sys.exit("project venv missing: python3 -m venv .venv && .venv/bin/pip install mlx-lm")

    cmd = [
        str(python), "-m", "mlx_lm", "lora",
        "--model", args.base,
        "--train",
        "--data", args.data,
        "--adapter-path", args.adapter,
        "--iters", str(args.iters),
        "--num-layers", str(args.layers),
        "--batch-size", str(args.batch_size),
        "--learning-rate", str(args.learning_rate),
    ]
    print(" ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
