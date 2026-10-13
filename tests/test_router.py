#!/usr/bin/env python3
"""Checks hook accuracy and Jev accuracy on tests/cases.json.

  python3 tests/test_router.py            # hook + Jev (needs OPENROUTER_API_KEY)
  python3 tests/test_router.py --offline  # hook only
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import router  # noqa: E402

CASES = json.loads((ROOT / "tests" / "cases.json").read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    skills = router.load_skills()
    hook_ok = jev_ok = 0
    print(f"{'expected':<22}{'hook':<22}{'jev':<22}prompt")
    for case in CASES:
        expected = case["expected_skill"]
        hook = router.hook_pick(case["prompt"], skills)
        hook_pick = hook[0] if hook else None
        hook_ok += hook_pick == expected

        jev_pick = "-"
        if not args.offline:
            record, _ = router.route(case["prompt"])
            jev_pick = record["jev_skill"] if not record["fallback"] else "FALLBACK"
            jev_ok += jev_pick == expected

        print(f"{str(expected):<22}{str(hook_pick):<22}{str(jev_pick):<22}{case['prompt'][:50]}")

    total = len(CASES)
    print(f"\nhook: {hook_ok}/{total}")
    if not args.offline:
        print(f"jev:  {jev_ok}/{total}")


if __name__ == "__main__":
    main()
