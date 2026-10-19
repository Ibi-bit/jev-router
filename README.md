# jev-router

A prompt router for AI coding agents. For each prompt it:

1. Scores the installed skills against the prompt with cheap keyword matching.
2. Asks the Jev decision API (or a local trained model) to pick one skill and one model from a short list. Jev also picks a thinking level (`none`, `low`, `medium`, `high`) and whether to run inline or in a subagent.
3. Switches the model and thinking level (OpenCode only), adds the skill's instructions to the prompt, or runs the prompt in a fresh subagent session.

Every decision is appended to `routing-log.jsonl`, and the OpenCode plugin also logs per-call token usage and cost there. Routing takes the session's context size into account: switching models re-reads the whole context at full input price, so staying on the current model is often cheapest. See [docs/routing.md](docs/routing.md).

## 🧠 The "Local Brain" Feature

Instead of calling an external API (Jev) to decide which skill to use, **you can train a local model on your own codebase.** 

The included `train-router` skill allows you to:
1. **Scan** your project for all available `SKILL.md` files.
2. **Generate** a synthetic training dataset of prompts based on those skills.
3. **Train** a specialized "router model" (LoRA adapter) locally on your Mac.
4. **Run** the router entirely offline, replacing the Jev API with a local model that understands your specific project's capabilities.

This turns your router from a general-purpose tool into a specialist for your specific repository. See [docs/training.md](docs/training.md) for the full pipeline.

## Supported harnesses

| Harness | Adapter | Can switch model | Can add skill context | Status |
| --- | --- | --- | --- | --- |
| OpenCode | [`adapters/opencode/index.ts`](adapters/opencode/index.ts) | Yes, plus thinking level | Yes (rewrites the prompt); subagent mode | Loads; per-prompt routing not yet confirmed end to end |
| VS Code (Copilot agent hooks) | [`adapters/vscode/hooks.json`](adapters/vscode/hooks.json) | No | Advisory message only | Hook runs from the CLI; not checked in a live VS Code session |
| Claude Code | [`adapters/claude-code/settings.json`](adapters/claude-code/settings.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Codex CLI | [`adapters/codex/hooks.json`](adapters/codex/hooks.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Gemini CLI | [`adapters/gemini-cli/settings.json`](adapters/gemini-cli/settings.json) | No | Yes, as `additionalContext` | Output shape from docs; not run in a live session |
| Cursor | [`adapters/cursor/hooks.json`](adapters/cursor/hooks.json) | No | No (output format not verified) | Hook runs; advisory output only |

Hook-based harnesses only let a hook observe the prompt. They cannot change the model, so for them
the router only suggests a skill and model. Only OpenCode applies the decision.

## Skills

A skill is a folder containing a `SKILL.md` file. The router reads every `*/SKILL.md` under the directories
listed in `skill_dirs` in `config.json`:

```
test-skills/
  test-code-review/
    SKILL.md
```

Each `SKILL.md` starts with YAML frontmatter. The `name` and `description` fields are used for matching,
and the text after the frontmatter is the skill body:

```markdown
---
name: test-code-review
description: Review code for bugs, security issues and style problems. Use when asked to review a pull request, audit a function or find problems in source code.
---

Review the code and list findings as bugs, security issues and style notes, most serious first.
```

When a skill is picked, the prompt becomes the skill body, then `---`, then `Task:` and the original prompt.
Hook-based harnesses only show the skill name as a suggestion in `additionalContext`.

Hook adapters also scan the project-level `hook_skill_dirs` (`.agents/skills`, `.claude/skills`,
`.codex/skills`, `.gemini/skills`, `.opencode/skills`), so skills installed for each harness are found.

## Subagents

The decider can run a prompt in a **subagent** instead of inline. This is chosen per prompt (`mode`
`m2`), and it is best for self-contained questions that don't need the earlier messages in the session.

1. The router sends the subagent only the question, plus the skill body if one was picked. It does not
   send the session history.
2. The OpenCode plugin creates a fresh session (`jev-router subagent`) on the chosen model, with the
   chosen thinking level, and waits for it to finish. The wait times out after 300 seconds.
3. The subagent's answer is appended to the session prompt, so the main session sees the result.
4. If the subagent fails or times out, the prompt is sent unchanged and the error is logged.

Subagent runs log their own usage and cost in `routing-log.jsonl`, the same as inline runs. Hook
adapters cannot create sessions, so they only report `mode` as advice.

## Quick start

Requirements: Python 3.9+, and `OPENROUTER_API_KEY` in the environment.

```sh
git clone <this repo> ~/jev-router
export OPENROUTER_API_KEY=...   # set this in your shell profile
python3 ~/jev-router/tests/test_hooks.py     # offline checks
python3 ~/jev-router/router.py "Add a pause screen to the game"
```

Then install the adapter for your harness. See [docs/harnesses.md](docs/harnesses.md).

If `OPENROUTER_API_KEY` is missing or the Jev call fails, the router uses `default_model_key` (currently `glm`) and
no skill. It never blocks a prompt.

## Layout

```
router.py              routing logic and CLI (also the hook entry point)
config.json            models, skill directories, Jev endpoint
test-skills/           example skills for testing
tests/
  test_hooks.py        offline tests for every harness's hook output
  test_router.py       hook and Jev accuracy on tests/cases.json
  test_local_decider.py  offline tests for the trained-adapter decider
  cases.json           labelled prompts
adapters/              per-harness config files and the OpenCode plugin
skills/train-router/   skill and scripts that build and train the local router
docs/                  harness setup, configuration, routing behaviour, training
```

## Cost

Only the models listed in `config.json` can be chosen, and Jev only ever picks from that list.
Each prompt makes one Jev call plus one call to the chosen model (subagent mode runs that call in a fresh session).
The default model is `glm`, and the decider is `~perplexity/pplx-decider-flash-latest`. See [docs/configuration.md](docs/configuration.md)
for how to set the model list and spending limits.

## Docs

- [Harness setup](docs/harnesses.md)
- [Configuration](docs/configuration.md)
- [How routing works](docs/routing.md)
- [Training a local router](docs/training.md) — trained on WormsDestruction skills (100 iters, 4 layers); adapter saved at `adapters/router/`; eval accuracy 51.3% (39/76)
