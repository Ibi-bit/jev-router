# How routing works

For each prompt:

1. **Load skills.** Every `*/SKILL.md` under the skill directories is read. The YAML frontmatter
   `description` is used for matching.
2. **Keyword candidates.** `hook_pick` scores each skill: 2 points per prompt word that matches the
   skill's name (ignoring words shared by every skill name), and 1 point per word that matches its
   description. The top `hook_top_k` skills with a score above zero are kept.
3. **Skill decision.** Two deciders exist, chosen by `decider.type` in `config.json`.
   - `jev` (default): the Jev decision described below.
   - `local`: a trained adapter served by mlx-lm answers with one skill name or `none`. It picks no model;
     the model comes from `decider.model_key`. See [training.md](training.md).

   **Jev decision.** The router sends the prompt and every (skill, model) combination to the decider as
   `o1 … oN` options. The decider returns the chosen option and a confidence. The skill-free option is
   always included.

   The same call asks two more questions:
   - `thinking` (`t1…t4`): how much reasoning the chosen model should use (`none`, `low`, `medium`,
     `high`). Only applied to models with `"thinking": true`; passed to OpenCode as the model variant.
   - `mode` (`m1`/`m2`): run **inline** in the ongoing session, or in a **subagent**. A subagent gets a
     fresh context holding only the question (plus skill text); its answer is appended to the session
     prompt. Best for self-contained questions that don't need the session's earlier messages.

   **Session-aware pricing.** When the OpenCode plugin routes a prompt it passes the current session
   context size and the model the session is running on. Options that would switch models get a
   `SWITCHING COST` note in their criterion: the new model re-reads the whole context at full input
   price, while the session model's cached input is roughly 10x cheaper (measured 2026-10: a 2.4k-token
   cached haiku call cost $0.000033 vs $0.000250 for the first glm call on the same context). Staying on
   the session model is therefore usually cheapest; switching only pays when the cheaper model's rate
   saves more than the re-read costs, or the prompt runs in a subagent with no session context at all.
4. **Fallback.** If the key is missing, the request fails, or the decider returns an unknown choice, the
   router uses `default_model_key` with no skill, `thinking` `none` and `mode` `inline`, and records
   `"fallback": true`.
5. **Apply.** The OpenCode plugin switches the session model (with the thinking level as the model
   variant) and prepends the skill body to the prompt. In `subagent` mode it instead creates a fresh
   in-process session (`ctx.session.create` + `prompt` + `wait`) on the chosen model, logs that
   session's usage too, and appends the subagent's answer to the session prompt. Hook adapters only
   output the decision as context.
6. **Log.** One JSON line is appended to `routing-log.jsonl` with the prompt, candidates, pick, model,
   thinking, mode, latency and any error. The log contains your prompts, so keep it out of version
   control. It is in `.gitignore`.
7. **Usage.** Before each routed prompt, the plugin reads the session's last assistant message
   (`GET /api/session/{id}/message?limit=6&order=desc`) and appends a `"type": "usage"` record with the
   model, `tokens` (input, output, reasoning, cache read/write) and dollar `cost`. This is what makes
   the "does the router save credits?" question measurable: compare routed costs against a baseline
   where every turn runs on one fixed model.

## Reading the log

- `"agree": true` means the decider chose the same skill as the keyword match.
- `"fallback": true` means the decider was not used. Check `"error"`.
- `"skill_loaded": null` means the prompt went through without a skill.
- `"thinking"` is the applied reasoning level or `null` when the model doesn't support it;
  `"thinking_choice"` is what the decider picked.
- `"mode"` is `inline` or `subagent`; `"session_tokens"` is the session context size seen at routing time.
- `"type": "usage"` lines record one model call's tokens and cost (see above).

## Testing routing accuracy

`tests/cases.json` has labelled prompts. `python3 tests/test_router.py --offline` checks the keyword
step only. Without `--offline` it also calls Jev and prints both results.
