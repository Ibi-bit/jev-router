#!/usr/bin/env python3
"""Offline tests for prompt-hook output in every supported harness.

  python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import router  # noqa: E402


def run_hook(payload, harness):
    """Run hook_main with a payload on stdin and return the parsed stdout."""
    out = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(out):
        router.hook_main(harness)
    return json.loads(out.getvalue())


class HookTests(unittest.TestCase):
    def setUp(self):
        # No API key: Jev is skipped and the router falls back to the default model, offline.
        self.env = mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""})
        self.env.start()
        self.log = Path(tempfile.mkdtemp()) / "routing-log.jsonl"
        self.log_patch = mock.patch.object(router, "LOG", self.log)
        self.log_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.env.stop()

    def test_vscode_uses_system_message_only(self):
        result = run_hook({"prompt": "hello", "cwd": str(ROOT)}, "vscode")
        self.assertIn("systemMessage", result)
        self.assertNotIn("hookSpecificOutput", result)

    def test_claude_adds_user_prompt_submit_context(self):
        result = run_hook({"prompt": "hello", "cwd": str(ROOT)}, "claude")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("Jev suggests skill", result["hookSpecificOutput"]["additionalContext"])

    def test_codex_uses_user_prompt_submit(self):
        result = run_hook({"prompt": "hello", "cwd": str(ROOT)}, "codex")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_gemini_uses_before_agent(self):
        result = run_hook({"prompt": "hello", "cwd": str(ROOT)}, "gemini")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "BeforeAgent")

    def test_cursor_never_blocks(self):
        result = run_hook({"prompt": "hello", "workspace_roots": [str(ROOT)]}, "cursor")
        self.assertEqual(result, {"continue": True})

    def test_cursor_falls_back_to_workspace_root(self):
        self.assertEqual(run_hook({"prompt": "hi", "workspace_roots": [str(ROOT)]}, "cursor"), {"continue": True})

    def test_bad_payload_still_lets_prompt_through(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("not json")), redirect_stdout(out):
            router.hook_main("claude")
        self.assertEqual(json.loads(out.getvalue()), {})

    def test_every_harness_is_registered(self):
        self.assertEqual(set(router.HARNESSES), {"vscode", "claude", "codex", "gemini", "cursor"})


if __name__ == "__main__":
    unittest.main()
