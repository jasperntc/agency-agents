#!/usr/bin/env python3
"""check_readme_roster.py -- the README roster matches the registry.

    ./scripts/check_readme_roster.py

The README carries a table of every agent: emoji, name, link, Specialty, When to
Use. It is the front door of the repository and the largest hand-maintained
artifact in it.

WHY THIS VALIDATES RATHER THAN GENERATES

The original plan was to generate the roster from the registry and delete the
hand-maintained table. Measuring it first showed that would destroy information:

  * Specialty        editorial. 0 of 270 match the frontmatter description.
  * When to Use      editorial. Exists nowhere else.
  * emoji            editorial. 47 of 270 differ from the agent's frontmatter
                     emoji -- the README picks one that reads better in a table.

Only `name` and the link path are derivable. A generator would either delete
that writing or round-trip it, and a round-tripping generator guarantees nothing
a validator does not. So the roster stays hand-written and this enforces the
properties that actually matter:

  1. every agent in the registry has exactly one roster row
  2. every roster row links to a real agent
  3. no agent is listed twice
  4. the advertised agent count is correct

Property 4 is why this exists. The README advertised "230+ Specialized Agents"
while 270 shipped -- an exact, checked number goes stale loudly instead of
quietly.

Emoji divergence is reported, never failed: choosing a different emoji for the
table is an editorial decision, not a defect.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
REGISTRY = REPO_ROOT / "registry.json"

# This script prints emoji. Windows consoles default to cp1252, which cannot
# encode them, so an unguarded print crashes with UnicodeEncodeError -- exactly
# the defect repaired in check-agent-originality.sh (c29922b), reintroduced here
# because the same assumption is easy to make twice. Fixed at the source rather
# than by requiring callers to set PYTHONIOENCODING; a no-op where stdout is
# already UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROW = re.compile(r"^\| (\S+) \[([^\]]+)\]\(([^)]+)\) \| (.*?) \| (.*?) \|$", re.M)
COUNT = re.compile(r"\*\*(\d+) Specialized Agents\*\*")


def main() -> int:
    registry = json.loads(REGISTRY.read_bytes().decode("utf-8"))
    agents = {a["path"]: a for a in registry["agents"]}
    text = README.read_text(encoding="utf-8")
    rows = ROW.findall(text)

    errors, notes = [], []

    listed: dict[str, int] = {}
    for emoji, name, path, _spec, _when in rows:
        listed[path] = listed.get(path, 0) + 1
        if path not in agents:
            errors.append(f"roster links to a non-agent: {path} ({name})")
            continue
        if name != agents[path]["name"]:
            errors.append(f"{path}: roster says '{name}', registry says "
                          f"'{agents[path]['name']}'")
        if emoji != agents[path].get("emoji"):
            notes.append(f"{path}: roster emoji {emoji} differs from frontmatter "
                         f"{agents[path].get('emoji')}")

    for path, n in sorted(listed.items()):
        if n > 1:
            errors.append(f"listed {n} times: {path}")

    for path in sorted(set(agents) - set(listed)):
        errors.append(f"MISSING from the roster: {path} ({agents[path]['name']})")

    expected = registry["summary"]["agents"]
    m = COUNT.search(text)
    if not m:
        errors.append("no '**N Specialized Agents**' count found in the README "
                      "Stats section")
    elif int(m.group(1)) != expected:
        errors.append(f"README advertises {m.group(1)} agents, registry has "
                      f"{expected}")

    print(f"registry agents : {expected}")
    print(f"roster rows     : {len(rows)}")
    print(f"advertised count: {m.group(1) if m else '(none)'}")
    if notes:
        print(f"\nemoji differing from frontmatter: {len(notes)} "
              f"(editorial, not an error)")
        for n in notes[:3]:
            print(f"  {n}")
        if len(notes) > 3:
            print(f"  ... and {len(notes) - 3} more")

    if errors:
        print(f"\nFAILED: {len(errors)} roster error(s).\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print("\nPASSED: every agent appears exactly once, every link resolves, "
          "count is correct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
