#!/usr/bin/env python3
"""check_frontmatter.py -- validate every agent against the schema, and report
where the distribution layer disagrees with a real YAML parser.

    ./scripts/check_frontmatter.py            # validate + report
    ./scripts/check_frontmatter.py --strict   # also fail on advisories

Exit 1 on a parse failure or schema violation. Advisories and divergence are
reported but do not fail by default: they describe things that are valid per the
contract yet still wrong in practice, and the right response is usually a
deliberate decision rather than a red build.

Requires requirements-dev.txt. Never imported by the distribution path.
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import read_corpus  # noqa: E402
from lib.frontmatter import (  # noqa: E402
    FrontmatterError, advisories, divergence_report, load_schema, parse, validate,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true",
                    help="also exit 1 when there are advisories")
    ap.add_argument("--ref", help="git ref to check (default: working tree)")
    args = ap.parse_args()

    schema = load_schema()
    paths = sorted(read_corpus(args.ref))

    failures: list[tuple[str, str]] = []
    adv: dict[str, list[str]] = collections.defaultdict(list)
    kinds: collections.Counter[str] = collections.Counter()
    kind_fields: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)

    for path in paths:
        try:
            frontmatter, _, _ = parse(path)
        except FrontmatterError as exc:
            failures.append((path, str(exc)))
            continue
        for violation in validate(frontmatter, schema):
            failures.append((path, violation))
        for note in advisories(frontmatter):
            adv[note.split(":")[0]].append(f"{path}: {note}")
        for item in divergence_report(path):
            kinds[item["kind"]] += 1
            kind_fields[item["kind"]][item["field"]] += 1

    print(f"Checked {len(paths)} agents against schema/agent.schema.json\n")

    if kinds:
        print("Divergence from the legacy reader (scripts/lib.sh get_field):")
        for kind, n in kinds.most_common():
            fields = ", ".join(f"{f}x{c}" for f, c in kind_fields[kind].most_common())
            print(f"  {kind:22s} {n:>4}   ({fields})")
        print("  These are what the 14 converters actually see. Not errors --")
        print("  the distribution layer is unchanged by design -- but they bound")
        print("  what any consumer of generated output can rely on.\n")

    if adv:
        total = sum(len(v) for v in adv.values())
        print(f"Advisories ({total}) -- valid per the contract, wrong in practice:")
        for key in sorted(adv):
            print(f"  {key}: {len(adv[key])}")
            for line in adv[key][:4]:
                print(f"     {line}")
            if len(adv[key]) > 4:
                print(f"     ... and {len(adv[key]) - 4} more")
        print()

    if failures:
        print(f"FAILED: {len(failures)} violation(s).\n", file=sys.stderr)
        for path, msg in failures:
            print(f"  {path}: {msg}", file=sys.stderr)
        print("\nDo NOT loosen the schema to make this pass. It was derived from",
              file=sys.stderr)
        print("the corpus, so a violation means either a real defect in a file or",
              file=sys.stderr)
        print("a real change to the contract. Both need a decision.", file=sys.stderr)
        return 1

    if args.strict and adv:
        print("FAILED: advisories present and --strict was given.", file=sys.stderr)
        return 1

    print("PASSED: all agents parse and validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
