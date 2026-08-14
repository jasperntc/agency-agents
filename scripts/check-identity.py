#!/usr/bin/env python3
"""check-identity.py -- enforce the identity model.

    ./scripts/check-identity.py                       # working tree
    ./scripts/check-identity.py --base origin/main     # also check immutability

Four properties, all of which were previously assumed rather than enforced:

  1. Every agent has an `id`, matching ^[a-z0-9]+(-[a-z0-9]+)*$.
  2. Ids are globally unique.
  3. IMMUTABILITY -- an id present in the base ref must be unchanged. This is
     the one that matters. An id that can change is not an identity, and every
     downstream artifact keyed to it (versions, evaluation results, aliases,
     rollback) silently detaches.
  4. Both LEGACY namespaces stay unique and non-colliding:
       filename stems  -- strategy/runbooks.json rosters, README links, and the
                          install destination for claude-code and copilot
       name-slugs      -- all 14 converters, the Hermes index, install --agent
     Neither had any uniqueness check. build-hermes-plugin.py guards name-slugs
     only, only for its own build, and only when that build runs.

Exit 1 on any violation.
"""
from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import REPO_ROOT, read_corpus  # noqa: E402
from lib.frontmatter import parse  # noqa: E402
from inventory import slugify_lib_sh  # noqa: E402

ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def ids_at(ref: str) -> dict[str, str]:
    """Map path -> id at a git ref. Silently skips unparseable files: the base
    ref is history, and this check is about what changed, not about relitigating
    whether the past was valid."""
    out = {}
    for path, raw in read_corpus(ref).items():
        for line in raw.decode("utf-8").split("\n")[1:]:
            if line == "---":
                break
            if line.startswith("id: "):
                out[path] = line[4:].strip()
                break
    return out


def merge_base(base: str) -> str | None:
    proc = subprocess.run(["git", "merge-base", "HEAD", base],
                          cwd=REPO_ROOT, capture_output=True)
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="ref to check id immutability against")
    args = ap.parse_args()

    corpus = read_corpus(None)
    errors: list[str] = []

    ids: dict[str, str] = {}
    stems: dict[str, list[str]] = collections.defaultdict(list)
    slugs: dict[str, list[str]] = collections.defaultdict(list)

    for path in sorted(corpus):
        try:
            frontmatter, _, _ = parse(REPO_ROOT / path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")
            continue

        agent_id = frontmatter.get("id")
        if not agent_id:
            errors.append(f"{path}: missing 'id'")
        elif not isinstance(agent_id, str) or not ID_PATTERN.match(agent_id):
            errors.append(f"{path}: id {agent_id!r} does not match "
                          f"{ID_PATTERN.pattern}")
        else:
            ids[path] = agent_id

        stems[path.rsplit("/", 1)[-1][:-3]].append(path)
        name = frontmatter.get("name", "")
        if isinstance(name, str) and name:
            slugs[slugify_lib_sh(name)].append(path)

    # 2. id uniqueness
    by_id: dict[str, list[str]] = collections.defaultdict(list)
    for path, agent_id in ids.items():
        by_id[agent_id].append(path)
    for agent_id, paths in sorted(by_id.items()):
        if len(paths) > 1:
            errors.append(f"duplicate id '{agent_id}': {', '.join(paths)}")

    # 4. legacy namespaces
    for stem, paths in sorted(stems.items()):
        if len(paths) > 1:
            errors.append(f"duplicate filename stem '{stem}': {', '.join(paths)}")
    for slug, paths in sorted(slugs.items()):
        if len(paths) > 1:
            errors.append(f"duplicate name-slug '{slug}': {', '.join(paths)}")
    cross = {s for s in stems if s in slugs and stems[s] != slugs[s]}
    for s in sorted(cross):
        errors.append(f"cross-namespace collision '{s}': it is the filename stem "
                      f"of {stems[s][0]} and the name-slug of {slugs[s][0]}")

    # 3. immutability
    checked_base = None
    if args.base:
        checked_base = merge_base(args.base) or args.base
        for path, was in ids_at(checked_base).items():
            now = ids.get(path)
            if now is None:
                # File removed or renamed. Not an id change per se, but the id
                # has lost its file, which downstream artifacts still reference.
                errors.append(f"{path}: had id '{was}' at {args.base} but is gone "
                              f"now. An id must outlive a move -- carry it to the "
                              f"new path rather than dropping it.")
            elif now != was:
                errors.append(f"{path}: id changed '{was}' -> '{now}'. Ids are "
                              f"immutable; everything keyed to the old value "
                              f"detaches silently.")

    print(f"agents: {len(corpus)}   ids: {len(ids)}   "
          f"stems: {len(stems)}   name-slugs: {len(slugs)}")
    mismatch = sum(1 for p, i in ids.items()
                   if i != slugify_lib_sh(parse(REPO_ROOT / p)[0].get("name", "")))
    print(f"ids differing from their name-slug: {mismatch} "
          f"({mismatch * 100 // max(len(ids), 1)}%) -- expected, and the reason "
          f"a third identifier exists")
    if checked_base:
        print(f"immutability checked against: {checked_base[:12]}")

    if errors:
        print(f"\nFAILED: {len(errors)} identity error(s).\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print("\nPASSED: ids present, unique, well-formed; legacy namespaces "
          "collision-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
