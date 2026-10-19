#!/usr/bin/env python3
"""Prompt router: hook keyword scoring -> decider one-call model + skill + thinking + mode pick -> run.

Usage:
  python3 router.py "prompt"                      # print the routing decision and final prompt
  python3 router.py --run "prompt"                # also run it through `opencode run`
  python3 router.py --hook --harness claude < payload.json   # prompt-submit hook output
  python3 router.py --log-usage '{"model": "...", "tokens": {...}, "cost": 0.001}'   # append usage record
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


def price_note(key):
    model = CONFIG["models"][key]
    return f"~${model.get('price_in', 0):g}/M in, ~${model.get('price_out', 0):g}/M out"


def jev_decide(prompt, candidates, skills, session_tokens=0, session_model=None):
    """Ask the decider for a (skill, model) pick, a thinking level and an inline/subagent mode.

    session_tokens is the current session context size and session_model the model id the
    session has been running on. Both let the decider see the cost of switching models:
    a switched-to model re-reads the whole context at full input price, while the session
    model's cached input is roughly 10x cheaper.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    session_ids = {m["id"] for m in CONFIG["models"].values()}
    switching = bool(session_tokens) and session_model in session_ids
    options = []
    for skill in candidates + [None]:
        for key, model in CONFIG["models"].items():
            label = f"skill {skill}" if skill else "no skill (raw prompt only)"
            note = ""
            if switching and model["id"] != session_model:
                cost = session_tokens * model.get("price_in", 0) / 1e6
                note = (f" SWITCHING COST: re-reads the ~{session_tokens}-token session context"
                        f" at full input price (~${cost:.4f} extra); the session model's cached"
                        " input is ~10x cheaper, so prefer it unless the savings clearly win.")
            options.append({
                "skill": skill,
                "model": key,
                "criterion": f"{label}, run on model {key} ({price_note(key)}): {model['description']}.{note}",
            })
    criteria = {f"o{i + 1}": o["criterion"] for i, o in enumerate(options)}
    levels = CONFIG["thinking"]["levels"]
    thinking_criteria = {f"t{i + 1}": f"{level}: {desc}" for i, (level, desc) in enumerate(levels.items())}
    ctx = f" The ongoing session already holds ~{session_tokens} tokens of context." if session_tokens else ""
    mode_criteria = {
        "m1": f"inline: answer inside the ongoing session with its full context.{ctx}",
        "m2": ("subagent: run in a fresh context holding only the question (plus skill text);"
               " the answer text is added to the session afterwards. Best for self-contained"
               " questions that do not need the session's earlier messages or tool results."),
    }
    body = json.dumps({
        "model": CONFIG["jev"]["model"],
        "state": {"user_request": prompt},
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which skill and which model should handle this request best?",
                "criteria": criteria,
            },
            "thinking": {
                "type": "choice",
                "instructions": "How much reasoning should the chosen model use? Pick the lowest level that will still answer well.",
                "criteria": thinking_criteria,
            },
            "mode": {
                "type": "choice",
                "instructions": "Should this request run inline in the ongoing session, or in a fresh subagent?",
                "criteria": mode_criteria,
            },
        },
    }).encode()
    req = urllib.request.Request(CONFIG["jev"]["url"], data=body, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=CONFIG["jev"]["timeout_s"]) as resp:
        answers = json.load(resp)["answers"]
    answer = answers["route"]
    by_key = dict(zip(criteria, options))
    if answer["choice"] not in by_key:
        raise ValueError(f"unknown Jev choice: {answer['choice']!r}")
    chosen = by_key[answer["choice"]]
    thinking_answer = answers.get("thinking", {}).get("choice")
    thinking = dict(zip(thinking_criteria, levels))
    thinking_level = thinking.get(thinking_answer, CONFIG["thinking"]["default"])
    mode_answer = answers.get("mode", {}).get("choice")
    mode = {"m1": "inline", "m2": "subagent"}.get(mode_answer, "inline")
    return chosen, answer["confidence"], thinking_level, mode


def local_decide(prompt, skills):
    """Ask a locally served adapter (mlx-lm server) for the skill name, or None."""
    cfg = CONFIG["decider"]
    listing = "\n".join(f"- {s['name']}: {s['description']}" for s in sorted(skills.values(), key=lambda s: s["name"]))
    system = (
        f"Available skills:\n{listing}\n"
        "Answer with exactly one skill name from this list, or 'none' if no skill fits."
    )
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": 12,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(cfg["url"], data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=cfg.get("timeout_s", 10)) as resp:
        answer = json.load(resp)["choices"][0]["message"]["content"].strip()
    if answer == "none":
        return None
    if answer not in skills:
        raise ValueError(f"unknown local skill: {answer!r}")
    return answer


def route(prompt, skill_dirs=None, session_tokens=0, session_model=None):
    start = time.time()
    skills = load_skills(skill_dirs)
    picks = hook_pick(prompt, skills)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": prompt,
        "hook_candidates": picks,
        "hook_pick": picks[0] if picks else None,
    }
    if CONFIG.get("decider", {}).get("type") == "local":
        try:
            skill = local_decide(prompt, skills)
            model_key = CONFIG["decider"].get("model_key", CONFIG["default_model_key"])
            record.update(jev_skill=skill, model_key=model_key, jev_confidence=None, thinking_choice=CONFIG["thinking"]["default"], mode="inline", fallback=False, error=None)
        except Exception as exc:  # local server down or bad answer: default model, no skill
            record.update(jev_skill=None, model_key=CONFIG["default_model_key"], thinking_choice=CONFIG["thinking"]["default"], mode="inline", fallback=True, error=str(exc))
    else:
        try:
            chosen, confidence, thinking_level, mode = jev_decide(prompt, picks, skills, session_tokens, session_model)
            record.update(jev_skill=chosen["skill"], model_key=chosen["model"], jev_confidence=confidence, thinking_choice=thinking_level, mode=mode, fallback=False, error=None)
        except Exception as exc:  # decider down or bad answer: default model, no skill
            record.update(jev_skill=None, model_key=CONFIG["default_model_key"], thinking_choice=CONFIG["thinking"]["default"], mode="inline", fallback=True, error=str(exc))

    model_key = record["model_key"]
    skill = record["jev_skill"]
    final_prompt = prompt
    subagent_prompt = None
    if skill:
        final_prompt = f"{skills[skill]['body']}\n\n---\nTask:\n{prompt}"
    thinking = record["thinking_choice"] if CONFIG["models"][model_key].get("thinking") else None
    if record["mode"] == "subagent":
        # The skill goes to the subagent, not the session prompt; the plugin appends
        # the subagent's answer to the session prompt.
        subagent_prompt = final_prompt
        final_prompt = prompt

    record.update(
        model=CONFIG["models"][model_key]["id"],
        skill_loaded=skill,
        thinking=thinking,
        session_tokens=session_tokens,
        agree=record["hook_pick"] == skill,
        latency_ms=round((time.time() - start) * 1000),
    )
    with LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record, final_prompt, subagent_prompt


def log_usage(data):
    """Append a usage record emitted by the OpenCode plugin after a model call."""
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "type": "usage",
        "sessionID": data.get("sessionID"),
        "model": data.get("model"),
        "tokens": data.get("tokens"),
        "cost": data.get("cost"),
    }
    with LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


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
        record, _, _ = route(payload["prompt"], skill_dirs)
        skill = record["skill_loaded"] or "none"
        message = f"Jev suggests skill: {skill}; model: {record['model_key']} ({record['model']}); thinking: {record['thinking'] or 'none'}."
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
    parser.add_argument("--session-tokens", type=int, default=0, help="current session context size, for cache-aware routing")
    parser.add_argument("--session-model", default=None, help="model id the session currently runs on (config id form)")
    parser.add_argument("--log-usage", dest="log_usage", metavar="JSON", help="append a usage record to the routing log and exit")
    args = parser.parse_args()
    if args.log_usage is not None:
        log_usage(json.loads(args.log_usage))
        return
    if args.hook:
        hook_main(args.harness)
        return
    if args.prompt is None:
        parser.error("a prompt is required unless --hook is used")

    record, final_prompt, subagent_prompt = route(args.prompt, args.skills_dir, args.session_tokens, args.session_model)
    if args.json:
        print(json.dumps({
            "model": record["model"],
            "skill": record["skill_loaded"],
            "thinking": record["thinking"],
            "mode": record["mode"],
            "prompt": final_prompt,
            "subagent_prompt": subagent_prompt,
        }))
        return
    print(json.dumps({k: record[k] for k in ("hook_candidates", "hook_pick", "jev_skill", "model_key", "model", "thinking", "mode", "fallback", "error", "latency_ms")}, indent=2))
    if args.run:
        subprocess.run(["opencode", "run", "--model", record["model"], final_prompt], check=False)


if __name__ == "__main__":
    main()
