#!/usr/bin/env python3
"""add_id.py -- one-time migration: give every agent an immutable canonical id.

    ./scripts/migrate/add_id.py --dry-run    # report, write nothing
    ./scripts/migrate/add_id.py              # apply

WHY

The repository has two identity namespaces, both load-bearing, and they disagree
for 198 of 270 agents (73%):

  filename stem   engineering-frontend-developer   install_claude_code and
                                                   install_copilot destination
                                                   names, strategy/runbooks.json
                                                   rosters, every README link
  name-slug       frontend-developer               all 14 converters, the Hermes
                                                   index, install.sh --agent

Both move under ordinary edits. Renaming a file breaks runbooks and README
links; changing `name:` silently re-homes generated files for 13 of 16 tools and
orphans whatever was installed previously. Nothing downstream -- versioning,
evaluation results, deprecation, rollback -- can be keyed to something that
moves.

So we add a THIRD identifier that is explicit and never changes.

    id     immutable identity    never changes, survives moves and renames
    path   filesystem location   may change
    name   display name          may change
    legacy slugs                 derived, frozen, for backwards compatibility

HOW

id is seeded to the filename stem VERBATIM. That is a deliberate choice
(decision D2): strategy/runbooks.json already keys on the stem, so seeding this
way costs zero migration for a live consumer. Stems are not uniformly
division-prefixed -- game-development/unity/unity-architect.md has the stem
"unity-architect" -- and they are NOT normalised here. Consistency of form is
worth less than compatibility with a working consumer, and id is decoupled from
path going forward, so the inconsistency never grows.

SAFETY

The insertion is surgical TEXT manipulation, not a YAML round trip. Re-emitting
frontmatter through a YAML dumper would reformat every file -- reordering keys,
changing quoting, normalising unicode -- turning a one-line addition into 270
uncontrolled rewrites. Instead a single line is inserted after the opening
fence, and every other byte is left exactly as it was.

Idempotent: a file that already has an id is skipped. Refuses to write anything
if any id would be duplicated.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.corpus import REPO_ROOT, read_corpus  # noqa: E402
from lib.frontmatter import parse  # noqa: E402

ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def stem_of(path: str) -> str:
    return path.rsplit("/", 1)[-1][:-3]


def plan(corpus: dict[str, bytes]) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (files_to_change, problems). Writes nothing."""
    todo, problems, seen = [], [], {}

    for path in sorted(corpus):
        stem = stem_of(path)
        if not ID_PATTERN.match(stem):
            problems.append(f"{path}: stem '{stem}' is not a valid id "
                            f"(must match {ID_PATTERN.pattern})")
            continue
        if stem in seen:
            problems.append(f"duplicate id '{stem}': {seen[stem]} and {path}")
            continue
        seen[stem] = path

        try:
            frontmatter, _, _ = parse(REPO_ROOT / path)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the survey
            problems.append(f"{path}: {exc}")
            continue

        existing = frontmatter.get("id")
        if existing is None:
            todo.append((path, stem))
        elif existing != stem:
            problems.append(f"{path}: already has id '{existing}', expected '{stem}'. "
                            f"An id is immutable -- resolve this by hand.")
        # existing == stem -> already migrated, nothing to do

    return todo, problems


def apply_one(path: str, agent_id: str) -> None:
    """Insert `id: <agent_id>` as the first frontmatter key.

    Byte-exact apart from the inserted line: the file is split on the opening
    fence and rejoined, so nothing else is re-encoded or reformatted.
    """
    full = REPO_ROOT / path
    raw = full.read_bytes().decode("utf-8")
    lines = raw.split("\n")
    if lines[0] != "---":
        raise SystemExit(f"{path}: does not open with '---'")
    lines.insert(1, f"id: {agent_id}")
    full.write_bytes("\n".join(lines).encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    corpus = read_corpus(None)
    todo, problems = plan(corpus)

    print(f"agents: {len(corpus)}")
    print(f"already have an id: {len(corpus) - len(todo) - len(problems)}")
    print(f"to migrate: {len(todo)}")

    if problems:
        print(f"\nPROBLEMS ({len(problems)}) -- nothing written:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    if todo:
        print("\nsample:")
        for path, agent_id in todo[:5]:
            print(f"  {path}")
            print(f"     id: {agent_id}")
        # The interesting cases: stems that are not division-prefixed.
        odd = [(p, i) for p, i in todo if not i.startswith(p.split("/")[0])]
        if odd:
            print(f"\nids that do NOT start with their division ({len(odd)}), kept "
                  f"verbatim by design:")
            for path, agent_id in odd[:8]:
                print(f"  {path}  ->  {agent_id}")
            if len(odd) > 8:
                print(f"  ... and {len(odd) - 8} more")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    for path, agent_id in todo:
        apply_one(path, agent_id)
    print(f"\nInserted an id into {len(todo)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
