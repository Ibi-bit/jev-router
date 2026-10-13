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

   **Jev decision.** The router sends the prompt and every (skill, model) combination to Jev as
   `o1 … oN` options. Jev returns the chosen option and a confidence. The skill-free option is always
   included.
4. **Fallback.** If the key is missing, the request fails, or Jev returns an unknown choice, the router
   uses `default_model_key` with no skill and records `"fallback": true`.
5. **Apply.** The OpenCode plugin switches the session model and prepends the skill body to the prompt.
   Hook adapters only output the decision as context.
6. **Log.** One JSON line is appended to `routing-log.jsonl` with the prompt, candidates, pick, model,
   latency and any error. The log contains your prompts, so keep it out of version control. It is in
   `.gitignore`.

## Reading the log

- `"agree": true` means Jev chose the same skill as the keyword match.
- `"fallback": true` means Jev was not used. Check `"error"`.
- `"skill_loaded": null` means the prompt went through without a skill.

## Testing routing accuracy

`tests/cases.json` has labelled prompts. `python3 tests/test_router.py --offline` checks the keyword
step only. Without `--offline` it also calls Jev and prints both results.
