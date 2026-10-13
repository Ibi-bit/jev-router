#!/usr/bin/env python3
"""Generate routing training data from a skills list.

  python3 make_dataset.py skills.json --out data/ [--per-skill 25] [--negatives 40] [--max-calls 30]

For each skill, asks a cheap model for prompts that skill should handle. Also asks for prompts
that no skill should handle (label "none"). Writes train.jsonl and valid.jsonl in the chat format
used by mlx_lm: the system message lists every skill, the user message is the prompt, and the
assistant message is the correct skill name or "none".
"""
import argparse
import json
import os
import random
import sys
import urllib.request
from pathlib import Path

ROUTER_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROUTER_ROOT))
import router  # noqa: E402

API = "https://openrouter.ai/api/v1/chat/completions"


class Budget:
    def __init__(self, max_calls, api_key):
        self.left = max_calls
        self.api_key = api_key
        self.tokens = 0

    def ask(self, model, instruction):
        if self.left <= 0:
            raise RuntimeError("max-calls reached; raise --max-calls to generate more")
        self.left -= 1
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": instruction}],
            "temperature": 1.0,
        }).encode()
        req = urllib.request.Request(API, data=body, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        self.tokens += data.get("usage", {}).get("total_tokens", 0)
        return data["choices"][0]["message"]["content"]


def parse_list(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[1]
    items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def catalogue(skills):
    lines = ["Available skills:"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    lines.append("Answer with exactly one skill name from this list, or 'none' if no skill fits.")
    return "\n".join(lines)


def positives(budget, model, skill, n):
    instruction = (
        f"You are writing training data for a router that picks skills for a coding assistant.\n"
        f"Skill name: {skill['name']}\nSkill description: {skill['description']}\n\n"
        f"Write {n} different messages a developer might send that this skill should handle. "
        f"Vary the wording, length and detail. Include some without naming the skill, and a few with typos. "
        f"Return only a JSON array of strings."
    )
    return parse_list(budget.ask(model, instruction))


def negatives(budget, model, skills, n):
    names = "; ".join(f"{s['name']} ({s['description']})" for s in skills)
    instruction = (
        f"You are writing training data for a router that picks skills for a coding assistant.\n"
        f"The skills are: {names}\n\n"
        f"Write {n} messages a developer might send to the assistant that NONE of these skills should handle. "
        f"Include general questions, chit-chat, and tasks unrelated to any listed skill. "
        f"Return only a JSON array of strings."
    )
    return parse_list(budget.ask(model, instruction))


def example(system, prompt, label):
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": label},
    ]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("skills", help="skills.json from scan_skills.py")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--per-skill", type=int, default=25)
    parser.add_argument("--negatives", type=int, default=40)
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--valid-every", type=int, default=10, help="every Nth example goes to valid.jsonl")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY is not set")
    model = router.CONFIG.get("dataset_model", "anthropic/claude-haiku-5.5")
    if model.startswith("openrouter/"):
        model = model[len("openrouter/"):]

    skills = json.loads(Path(args.skills).read_text())
    system = catalogue(skills)
    budget = Budget(args.max_calls, api_key)
    examples = []
    for skill in skills:
        for prompt in positives(budget, model, skill, args.per_skill):
            examples.append(example(system, prompt, skill["name"]))
    for prompt in negatives(budget, model, skills, args.negatives):
        examples.append(example(system, prompt, "none"))

    seen = set()
    unique = []
    for ex in examples:
        prompt = ex["messages"][1]["content"]
        if prompt.lower() not in seen:
            seen.add(prompt.lower())
            unique.append(ex)
    random.Random(0).shuffle(unique)
    valid = [ex for i, ex in enumerate(unique) if (i + 1) % args.valid_every == 0]
    train = [ex for i, ex in enumerate(unique) if (i + 1) % args.valid_every != 0]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("valid.jsonl", valid)):
        with (out / name).open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    print(f"train {len(train)}  valid {len(valid)}  calls used {args.max_calls - budget.left}  tokens {budget.tokens}", file=sys.stderr)


if __name__ == "__main__":
    main()
