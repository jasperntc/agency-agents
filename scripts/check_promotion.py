#!/usr/bin/env python3
"""check_promotion.py -- a change may not degrade the agents it touches.

    ./scripts/check_promotion.py --base main      # CI: gate a pull request
    ./scripts/check_promotion.py --base main --json

Every other gate in this repository measures the corpus. That is the right shape
for a mass rewrite -- archive/fable-upgrade touched 263 files and moved corpus
medians hard enough to see. It is the wrong shape for the ordinary case: a pull
request that edits three agents cannot move a median over 270, so it passes every
existing check no matter what it does to those three.

This gate looks only at what the diff touched, and compares each changed agent
against its own previous self.

WHAT IT WILL AND WILL NOT JUDGE

It does not decide whether an edit made an agent better. Nothing mechanical can,
and a gate that pretends to would be worse than none -- people would trust it.

It fails on the narrow set of changes that are degradation under any reading:

  * an agent becoming measurably more similar to some other agent. Two
    specialists converging is a loss of specialization by definition. There is
    no version of "this edit improved things" that requires it.
  * an agent taking on more text that already appears verbatim in other agents.
    That is boilerplate arriving, which is how the Fable regression happened one
    file at a time.

Growth in length is reported and never fails. A rewritten agent legitimately
gets longer, and the corpus-level size ratchet already covers sustained bloat.

THE RATCHET (decision D6)

The second half of this script guards the gates themselves. Every threshold in
metrics/*thresholds.json may be tightened freely and may not be loosened -- a
raised max, a lowered min, or a deleted entry all fail the build.

Without this, every gate in the repository is advisory in practice: the cheapest
way to land a change that trips a threshold is to edit the threshold in the same
commit, and in a large diff nobody notices. The ratchet does not make that
impossible, it makes it explicit -- add `loosened_why` to the entry and the build
passes, with the justification sitting in the diff where a reviewer reads it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_diversity as cd  # noqa: E402
from lib.corpus import REPO_ROOT, dump_json, read_corpus, resolve_ref  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

THRESHOLDS = REPO_ROOT / "metrics" / "promotion-thresholds.json"

# Every file the ratchet guards. A gate whose thresholds are not listed here can
# be silently loosened, so adding a new *thresholds.json must add it here too --
# tests/test_check_promotion.py asserts this list covers metrics/.
RATCHETED = (
    "metrics/thresholds.json",
    "metrics/routing-thresholds.json",
    "metrics/promotion-thresholds.json",
)


def git(args: list[str], check: bool = True) -> str:
    proc = subprocess.run(["git"] + args, cwd=REPO_ROOT, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: "
                         f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("utf-8", "replace")


def merge_base(base: str) -> str:
    """The commit this branch diverged from, not the tip of the base branch.

    Comparing against the tip would attribute every change that landed on main
    since branching to this pull request. check-identity.py resolves its base the
    same way, deliberately.
    """
    resolved = resolve_ref(base)
    out = git(["merge-base", "HEAD", resolved], check=False).strip()
    return out or resolved


def changed_agents(base: str) -> dict[str, list[str]]:
    """Agent files added, modified or removed between `base` and the work tree."""
    corpus_now = set(read_corpus(None))
    corpus_base = set(read_corpus(base))
    out: dict[str, list[str]] = {"added": [], "modified": [], "removed": []}

    raw = git(["diff", "--name-status", base, "--"])
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        if path not in corpus_now and path not in corpus_base:
            continue
        if status.startswith("A"):
            out["added"].append(path)
        elif status.startswith("D"):
            out["removed"].append(path)
        elif status.startswith(("M", "R", "C")):
            out["modified"].append(path)

    return {k: sorted(v) for k, v in out.items()}


def per_agent_boilerplate(ref: str | None) -> dict[str, float]:
    """Share of each agent's words sitting inside a run shared with other agents.

    corpus_diversity._boilerplate computes exactly this and then sums it into one
    corpus figure. The per-file breakdown is what a diff gate needs, so it is
    recomputed here from the same tokenizer and the same constants rather than
    approximated -- divergence between the two would be a defect in itself.

    NOTE ON ATTRIBUTION: the shared-block set is corpus-wide, so an agent's score
    can move because OTHER agents changed. That is real (text becomes boilerplate
    when someone else copies it) but it does mean a delta here is not always
    caused by the edit to that file. Documented in docs/promotion.md.
    """
    corpus = read_corpus(ref)
    paths = sorted(corpus)
    words = {p: cd.tokens(corpus[p].decode("utf-8")) for p in paths}

    counts: dict[str, int] = {}
    for p in paths:
        for block in cd.shingles(words[p], cd.BLOCK_K):
            counts[block] = counts.get(block, 0) + 1
    shared = {b for b, c in counts.items() if c >= cd.BLOCK_MIN_FILES}

    out: dict[str, float] = {}
    for p in paths:
        w = words[p]
        covered = bytearray(len(w))
        for i in range(max(0, len(w) - cd.BLOCK_K + 1)):
            if " ".join(w[i:i + cd.BLOCK_K]) in shared:
                for j in range(i, i + cd.BLOCK_K):
                    covered[j] = 1
        out[p] = round(sum(covered) / len(w) * 100, 4) if w else 0.0
    return out


_METRICS_CACHE: dict[str | None, dict] = {}


def agent_metrics(ref: str | None) -> dict[str, dict]:
    """Per-agent similarity, boilerplate share and length at one ref.

    Memoized: this runs a full pairwise pass over the corpus, and a single
    invocation measures the same ref more than once (base for the diff, base
    again for the ratchet). The tests compare several refs and would otherwise
    spend minutes recomputing identical numbers.
    """
    if ref in _METRICS_CACHE:
        return _METRICS_CACHE[ref]
    measured = cd.measure(ref)
    corpus = read_corpus(ref)
    boiler = per_agent_boilerplate(ref)
    out = {}
    for row in measured["per_agent"]:
        path = row["path"]
        out[path] = {
            "max_similarity_pct": row["max_similarity_pct"],
            "closest": row["closest"],
            "duplicated_word_pct": boiler.get(path, 0.0),
            "words": len(cd.tokens(corpus[path].decode("utf-8"))),
        }
    _METRICS_CACHE[ref] = out
    return out


# ---------------------------------------------------------------------------
# Per-agent regression
# ---------------------------------------------------------------------------

def review_agents(changed: dict, base: str, rules: dict,
                  head_ref: str | None = None) -> tuple[list, list, list]:
    """(failures, advisories, rows) for every agent the diff touched.

    `head_ref` exists so the test suite can point both ends at git refs and ask
    the question that matters: would this gate have stopped the Fable upgrade?
    In normal use head is the working tree.
    """
    targets = changed["added"] + changed["modified"]
    if not targets:
        return [], [], []

    head = agent_metrics(head_ref)
    prev = agent_metrics(base)

    failures, advisories, rows = [], [], []
    for path in sorted(targets):
        now = head.get(path)
        if now is None:
            continue
        was = prev.get(path)

        row = {
            "path": path,
            "state": "added" if was is None else "modified",
            "max_similarity_pct": now["max_similarity_pct"],
            "closest": now["closest"],
            "duplicated_word_pct": now["duplicated_word_pct"],
            "words": now["words"],
        }
        if was is not None:
            row["max_similarity_delta"] = round(
                now["max_similarity_pct"] - was["max_similarity_pct"], 4)
            row["duplicated_word_delta"] = round(
                now["duplicated_word_pct"] - was["duplicated_word_pct"], 4)
            row["word_delta_pct"] = round(
                (now["words"] - was["words"]) / was["words"] * 100, 2
            ) if was["words"] else 0.0
        rows.append(row)

        # Absolute ceilings apply to added and modified files alike: a brand new
        # agent that arrives already 25% similar to an existing one is the same
        # problem as an old one drifting there.
        cap = rules["agent.max_similarity_pct"]["max"]
        if now["max_similarity_pct"] > cap:
            failures.append(
                f"{path}: {now['max_similarity_pct']}% similar to "
                f"{now['closest']} (ceiling {cap}%)")

        cap = rules["agent.duplicated_word_pct"]["max"]
        if now["duplicated_word_pct"] > cap:
            failures.append(
                f"{path}: {now['duplicated_word_pct']}% of its words are text "
                f"that also appears in other agents (ceiling {cap}%)")

        if was is None:
            continue

        # Deltas only make sense for a file that existed before.
        cap = rules["agent.max_similarity_delta"]["max"]
        if row["max_similarity_delta"] > cap:
            failures.append(
                f"{path}: grew {row['max_similarity_delta']:+} points more "
                f"similar to {now['closest']} (limit +{cap}). Two specialists "
                f"converging is not an improvement under any reading.")

        cap = rules["agent.duplicated_word_delta"]["max"]
        if row["duplicated_word_delta"] > cap:
            failures.append(
                f"{path}: took on {row['duplicated_word_delta']:+} points of "
                f"text shared with other agents (limit +{cap}). This is how "
                f"boilerplate arrives -- one file at a time.")

        cap = rules["agent.word_growth_pct"]["max"]
        if row["word_delta_pct"] > cap:
            advisories.append(
                f"{path}: {row['word_delta_pct']:+}% longer. Not a failure -- "
                f"length is a cost to justify, not a defect.")

    return failures, advisories, rows


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------

def load_at(ref: str, path: str) -> dict | None:
    out = git(["show", f"{ref}:{path}"], check=False)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def compare_thresholds(rel: str, before: dict, after: dict) -> tuple[list, list]:
    """(failures, deliberate releases) between two versions of a threshold file.

    Pure, so the ratchet can be tested against literal dicts rather than by
    constructing git history. A gate whose own tests need elaborate setup does
    not get tested.
    """
    failures, released = [], []
    old = before.get("thresholds", {})
    new = after.get("thresholds", {})

    for key, rule in sorted(old.items()):
        if key not in new:
            failures.append(f"{rel}: threshold `{key}` was removed. Deleting a "
                            f"bound is the largest possible loosening of it.")
            continue
        now = new[key]
        excuse = now.get("loosened_why")
        deliberate = bool(excuse) and excuse != rule.get("loosened_why")

        for bound in ("max", "min"):
            if bound not in rule or bound not in now:
                continue
            worse = now[bound] > rule[bound] if bound == "max" \
                else now[bound] < rule[bound]
            if not worse:
                continue
            move = f"{rel}: `{key}` {bound} {rule[bound]} -> {now[bound]}"
            if deliberate:
                released.append(f"{move}\n      because: {excuse}")
            else:
                failures.append(
                    f"{move} loosens the gate.\n"
                    f"      Tighten the change instead. If the looser bound is "
                    f"genuinely correct, add a `loosened_why` field to that "
                    f"entry saying why -- it will pass, and the reason will sit "
                    f"in the diff where a reviewer reads it.")

    return failures, released


def review_ratchet(base: str) -> tuple[list, list]:
    """(failures, deliberate releases) across every ratcheted threshold file."""
    failures, released = [], []

    for rel in RATCHETED:
        before = load_at(base, rel)
        if before is None:
            continue  # new file: nothing to loosen yet
        current_path = REPO_ROOT / rel
        if not current_path.exists():
            failures.append(f"{rel}: deleted. Removing a gate is the largest "
                            f"possible loosening.")
            continue
        after = json.loads(current_path.read_bytes().decode("utf-8"))
        f, r = compare_thresholds(rel, before, after)
        failures += f
        released += r

    return failures, released


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="main",
                    help="branch or ref this change is proposed against")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args()

    rules = json.loads(THRESHOLDS.read_bytes().decode("utf-8"))["thresholds"]
    base = merge_base(args.base)

    changed = changed_agents(base)
    agent_failures, advisories, rows = review_agents(changed, base, rules)
    ratchet_failures, released = review_ratchet(base)

    report = {
        "base": base,
        "changed": changed,
        "agents": rows,
        "failures": agent_failures + ratchet_failures,
        "advisories": advisories,
        "deliberate_releases": released,
    }

    if args.json:
        sys.stdout.buffer.write(dump_json(report))
        return 1 if report["failures"] else 0

    n = sum(len(v) for v in changed.values())
    print(f"Comparing against {base[:12]}")
    print(f"  agent files touched : {n} "
          f"({len(changed['added'])} added, {len(changed['modified'])} modified, "
          f"{len(changed['removed'])} removed)")

    if rows:
        print(f"\n{'agent':<52}{'sim%':>8}{'Δsim':>8}{'dup%':>8}{'Δdup':>8}"
              f"{'Δwords':>9}")
        for r in rows:
            name = r["path"].rsplit("/", 1)[-1][:-3]
            print(f"{name[:52]:<52}{r['max_similarity_pct']:>8}"
                  f"{r.get('max_similarity_delta', 0):>8}"
                  f"{r['duplicated_word_pct']:>8}"
                  f"{r.get('duplicated_word_delta', 0):>8}"
                  f"{r.get('word_delta_pct', 0):>8}%")

    if released:
        print(f"\nDELIBERATE THRESHOLD RELEASES ({len(released)}) -- allowed, "
              f"and recorded here so they are not silent:")
        for r in released:
            print(f"  {r}")

    if advisories:
        print(f"\nAdvisories ({len(advisories)}):")
        for a in advisories:
            print(f"  {a}")

    if report["failures"]:
        sys.stdout.flush()  # keep the table above the failures in CI logs
        print(f"\nFAILED: {len(report['failures'])} promotion check(s).\n",
              file=sys.stderr)
        for f in report["failures"]:
            print(f"  {f}", file=sys.stderr)
        return 1

    if n == 0:
        print("\nPASSED: no agent files changed; thresholds not loosened.")
    else:
        print(f"\nPASSED: {n} agent file(s) changed, none degraded, "
              f"no gate loosened.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
