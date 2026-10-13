# Harness setup

Each hook runs `router.py --hook --harness <name>`. The hook reads the prompt from stdin and prints
a JSON decision. It never blocks a prompt.

Commands below use `$HOME/jev-router`. If you cloned elsewhere, change the path in the adapter file.

## OpenCode

Copy the plugin into the project you want routed:

```sh
mkdir -p .opencode/plugins/jev-router
cp ~/jev-router/adapters/opencode/index.ts .opencode/plugins/jev-router/index.ts
```

Install the plugin's dependency in `.opencode/`:

```sh
cd .opencode && npm install @opencode/plugin@2.0.28
```

OpenCode loads plugins under `.opencode/plugins/` automatically. Watching the plugin file does not
reload its dependencies. If the plugin fails with `Cannot find package '@opencode/plugin'`, restart
the service with `opencode service restart`. Check `~/.local/share/opencode/log/opencode.log` for
`loading plugin` and `failed to load plugin`.

The plugin uses `JEV_ROUTER` if it is set, otherwise `~/jev-router/router.py`.

## VS Code (Copilot agent hooks)

Copy `adapters/vscode/hooks.json` to `<project>/.github/hooks/jev-router.json`.

## Claude Code

Add `adapters/claude-code/settings.json` to `~/.claude/settings.json`, or to `.claude/settings.json`
for one project. The hook uses the `UserPromptSubmit` event, which passes `prompt` and `cwd` on stdin.
The output uses `hookSpecificOutput.additionalContext`, which Claude Code adds to the context for that turn.

## Codex CLI

1. Enable hooks in `~/.codex/config.toml`:

   ```toml
   [features]
   codex_hooks = true
   ```

2. Copy `adapters/codex/hooks.json` to `~/.codex/hooks.json` or `<repo>/.codex/hooks.json`.
3. Run `/hooks` in Codex and trust the new hook. Codex skips non-managed hooks until they are trusted,
   and re-prompts when a hook's command changes.

## Gemini CLI

Merge `adapters/gemini-cli/settings.json` into `~/.gemini/settings.json` or `<project>/.gemini/settings.json`.
The hook uses `BeforeAgent`, which runs after the user submits a prompt. Gemini CLI fingerprints project hooks
and asks for review when a hook changes. Run `/hooks` to see it.

## Cursor

Copy `adapters/cursor/hooks.json` to `~/.cursor/hooks.json` or `<project>/.cursor/hooks.json`.
Cursor passes `workspace_roots` instead of `cwd`, and the router handles both.

Cursor's `beforeSubmitPrompt` output format was not confirmed from the docs, so the Cursor adapter
returns only `{"continue": true}`. It does not show the routing suggestion. Check Cursor's hook
schema before adding more output.

## Checking an install

Run the offline tests, then send a prompt in the harness and check `routing-log.jsonl`. A new line
with `"model"` and `"hook_candidates"` means the hook ran. If the harness has no such line, the hook
did not run. Check the harness's own hook log, such as `/hooks` in Codex or Gemini.
