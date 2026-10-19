#!/usr/bin/env python3
"""Offline tests for the local (trained adapter) decider.

  python3 -m unittest discover -s tests -v
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import router  # noqa: E402

SKILLS = {
    "wriggle-run-game": {"name": "wriggle-run-game", "description": "run the game", "body": "..."},
    "ponytail": {"name": "ponytail", "description": "lazy dev mode", "body": "..."},
}


LOCAL = {"type": "local", "url": "http://127.0.0.1:0/v1/chat/completions", "model": "m", "model_key": "fast"}


def fake_server(answer):
    payload = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
    return mock.patch("urllib.request.urlopen", return_value=io.BytesIO(payload))


class LocalDeciderTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(router.CONFIG, {"decider": LOCAL})
        patch.start()
        self.addCleanup(patch.stop)

    def test_returns_skill_name(self):
        with fake_server("ponytail"):
            self.assertEqual(router.local_decide("be lazy", SKILLS), "ponytail")

    def test_none_means_no_skill(self):
        with fake_server("none"):
            self.assertIsNone(router.local_decide("hi", SKILLS))

    def test_unknown_answer_raises(self):
        with fake_server("made-up-skill"):
            with self.assertRaises(ValueError):
                router.local_decide("x", SKILLS)

    def test_route_uses_local_when_configured(self):
        with mock.patch.object(router, "LOG", Path("/dev/null")), \
                mock.patch.object(router, "load_skills", return_value=SKILLS), fake_server("ponytail"):
            record, _, _ = router.route("be lazy")
        self.assertFalse(record["fallback"])
        self.assertEqual(record["model_key"], "fast")


if __name__ == "__main__":
    unittest.main()
