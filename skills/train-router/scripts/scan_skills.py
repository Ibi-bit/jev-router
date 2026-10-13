#!/usr/bin/env python3
"""List every skill the router can see, as JSON.

  python3 scan_skills.py <project-dir> [--out skills.json]

Reads skill directories from config.json (hook_skill_dirs, relative to the project)
and skill_dirs (absolute or ~), and prints name and description for each skill.
"""
import argparse
import json
import sys
from pathlib import Path

ROUTER_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROUTER_ROOT))
import router  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", help="project directory whose skills should be scanned")
    parser.add_argument("--out", help="write the list to this file instead of stdout")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    dirs = [str(project / d) for d in router.CONFIG.get("hook_skill_dirs", [])]
    dirs += [str(Path(d).expanduser()) for d in router.CONFIG.get("skill_dirs", [])]
    skills = router.load_skills(dirs)

    listing = [
        {"name": s["name"], "description": s["description"]}
        for s in sorted(skills.values(), key=lambda s: s["name"])
    ]
    text = json.dumps(listing, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"{len(listing)} skills -> {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
