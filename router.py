#!/usr/bin/env python3
"""Prompt router: hook keyword scoring -> Jev one-call model + skill pick -> run.

Usage:
  python3 router.py "prompt"                      # print the routing decision and final prompt
  python3 router.py --run "prompt"                # also run it through `opencode run`
  python3 router.py --hook --harness claude < payload.json   # prompt-submit hook output
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
LOG = HERE / "routing-log.jsonl"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
HARNESSES = ("vscode", "claude", "codex", "gemini", "cursor")
STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "what",
    "how", "can", "you", "please", "help", "make", "use", "some", "your", "are",
    "was", "not", "but", "all", "any", "out", "its", "our", "just", "need", "want",
}


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta, m.group(2)


def load_skills(skill_dirs=None):
    skills = {}
    for raw in skill_dirs or CONFIG["skill_dirs"]:
        for path in sorted(Path(raw).expanduser().glob("*/SKILL.md")):
            meta, body = parse_frontmatter(path.read_text())
            name = path.parent.name
            skills.setdefault(name, {
                "name": name,
                "description": meta.get("description", ""),
                "body": body.strip(),
            })
    return skills


def tokens(text):
    words = {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in re.findall(r"[a-z0-9]+", text.lower())}
    return {t for t in words if len(t) > 2 and t not in STOP}


def hook_pick(prompt, skills):
    prompt_tokens = tokens(prompt)
    name_tokens = {s["name"]: tokens(s["name"].replace("-", " ")) for s in skills.values()}
    shared = set.intersection(*name_tokens.values()) if name_tokens else set()
    scored = []
    for skill in skills.values():
        name_hits = prompt_tokens & (name_tokens[skill["name"]] - shared)
        desc_hits = prompt_tokens & tokens(skill["description"])
        score = 2 * len(name_hits) + len(desc_hits)
        if score > 0:
            scored.append((score, skill["name"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored[: CONFIG["hook_top_k"]]]


def jev_decide(prompt, candidates, skills):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    options = []
    for skill in candidates + [None]:
        for key, model in CONFIG["models"].items():
            label = f"skill {skill}" if skill else "no skill (raw prompt only)"
            options.append({
                "skill": skill,
                "model": key,
                "criterion": f"{label}, run on model {key}: {model['description']}",
            })
    criteria = {f"o{i + 1}": o["criterion"] for i, o in enumerate(options)}
    body = json.dumps({
        "model": CONFIG["jev"]["model"],
        "state": {"user_request": prompt},
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which skill and which model should handle this request best?",
                "criteria": criteria,
            }
        },
    }).encode()
    req = urllib.request.Request(CONFIG["jev"]["url"], data=body, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=CONFIG["jev"]["timeout_s"]) as resp:
        answer = json.load(resp)["answers"]["route"]
    by_key = dict(zip(criteria, options))
    if answer["choice"] not in by_key:
        raise ValueError(f"unknown Jev choice: {answer['choice']!r}")
    chosen = by_key[answer["choice"]]
    return chosen, answer["confidence"]


def route(prompt, skill_dirs=None):
    start = time.time()
    skills = load_skills(skill_dirs)
    picks = hook_pick(prompt, skills)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": prompt,
        "hook_candidates": picks,
        "hook_pick": picks[0] if picks else None,
    }
    try:
        chosen, confidence = jev_decide(prompt, picks, skills)
        record.update(jev_skill=chosen["skill"], model_key=chosen["model"], jev_confidence=confidence, fallback=False, error=None)
    except Exception as exc:  # Jev down or bad answer: default model, no skill
        record.update(jev_skill=None, model_key=CONFIG["default_model_key"], fallback=True, error=str(exc))

    model_key = record["model_key"]
    skill = record["jev_skill"]
    final_prompt = prompt
    if skill:
        final_prompt = f"{skills[skill]['body']}\n\n---\nTask:\n{prompt}"

    record.update(
        model=CONFIG["models"][model_key]["id"],
        skill_loaded=skill,
        agree=record["hook_pick"] == skill,
        latency_ms=round((time.time() - start) * 1000),
    )
    with LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record, final_prompt


def hook_output(harness, message):
    """Shape the advisory message for each harness's prompt hook. Never blocks the prompt."""
    if harness == "cursor":
        return {"continue": True}
    if harness == "vscode":
        return {"systemMessage": message} if message else {}
    event = "BeforeAgent" if harness == "gemini" else "UserPromptSubmit"
    if not message:
        return {}
    return {
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": message},
    }


def hook_main(harness="vscode"):
    """Read a prompt-submit payload from stdin and print an advisory routing message.

    Hooks cannot switch models, so the decision is only reported to the user and
    the agent as context. Any failure prints an empty decision so the prompt goes through.
    """
    try:
        payload = json.load(sys.stdin)
        cwd = payload.get("cwd") or (payload.get("workspace_roots") or ["."])[0]
        root = Path(cwd).expanduser().resolve()
        skill_dirs = [str(root / d) for d in CONFIG.get("hook_skill_dirs", [".agents/skills"])]
        record, _ = route(payload["prompt"], skill_dirs)
        skill = record["skill_loaded"] or "none"
        message = f"Jev suggests skill: {skill}; model: {record['model_key']} ({record['model']})."
        print(json.dumps(hook_output(harness, message)))
    except Exception:
        print(json.dumps(hook_output(harness, None)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--hook", action="store_true", help="prompt-submit hook mode: read the payload from stdin")
    parser.add_argument("--harness", choices=HARNESSES, default="vscode", help="output format for --hook")
    parser.add_argument("--run", action="store_true", help="run the prompt with opencode")
    parser.add_argument("--skills-dir", action="append", help="skill directory to use instead of config (repeatable)")
    parser.add_argument("--json", action="store_true", help="print model, skill and final prompt as JSON (for plugins)")
    args = parser.parse_args()
    if args.hook:
        hook_main(args.harness)
        return
    if args.prompt is None:
        parser.error("a prompt is required unless --hook is used")

    record, final_prompt = route(args.prompt, args.skills_dir)
    if args.json:
        print(json.dumps({"model": record["model"], "skill": record["skill_loaded"], "prompt": final_prompt}))
        return
    print(json.dumps({k: record[k] for k in ("hook_candidates", "hook_pick", "jev_skill", "model_key", "model", "fallback", "error", "latency_ms")}, indent=2))
    if args.run:
        subprocess.run(["opencode", "run", "--model", record["model"], final_prompt], check=False)


if __name__ == "__main__":
    main()
