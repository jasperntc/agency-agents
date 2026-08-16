#!/usr/bin/env python3
"""eval_selection.py -- does the model pick the right specialist?

    ./scripts/eval_selection.py                    # score every recorded run
    ./scripts/eval_selection.py --check            # CI: fail if the baseline is stale
    ./scripts/eval_selection.py --prompt c041      # print the blind prompt for one case
    ./scripts/eval_selection.py --template         # print the prompt template
    ./scripts/eval_selection.py --digest           # the tasks_sha256 a full run records

THE OTHER HALF OF PHASE 6

scripts/eval_routing.py measures whether the right specialist can be FOUND by
literal search -- 67.24% of tasks share a word with the right agent's index
line. It says nothing about the other third, because a model can translate
"second pair of eyes on this pull request" into `code review` before grepping
and the deterministic harness cannot.

This scores the translation and the choice: a real model, the real SKILL.md, the
real index, one pick per case. The payoff is not the accuracy number on its own
-- it is the cross-tab against reachability, which separates four different
outcomes that a single accuracy figure blends together. In particular,
`unreachable & correct` is the cell that proves query expansion works, and it is
the one Phase 6 could not measure even in principle.

WHY THE PICKS ARE A COMMITTED INPUT, NOT SOMETHING THIS SCRIPT PRODUCES

Answers come from a model, and models cost either money or session budget. If
this script called one, `--check` would be nondeterministic and CI could not run
it. So scoring is a pure function of (cases, responses): a run records its picks
into eval/selection/responses/<name>.json once, and the score is reproducible
forever after with no model in the loop.

That also makes the two runners interchangeable. A blind-subagent run inside a
Claude Code session and an API run with a key produce the same artifact and are
scored by the same code, so choosing the free path today does not fork the
measurement.

BLINDNESS IS THE WHOLE BALL GAME

Whoever answers must not see the expected agent. The prompt this file generates
carries the task text and nothing else -- no `expect`, no `why`, no case kind.
Every responses file records a sha256 of the task text it was answering, and
scoring refuses to run if it no longer matches, so picks collected against one
set of questions can never be quietly scored against a different set. See
tasks_digest() for why that hash covers the tasks rather than the whole file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_routing as er  # noqa: E402
from lib.corpus import REPO_ROOT, dump_json  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CASES = REPO_ROOT / "eval" / "routing" / "cases.jsonl"
RESPONSES = REPO_ROOT / "eval" / "selection" / "responses"
BASELINE = REPO_ROOT / "metrics" / "selection-baseline.json"
SKILL = REPO_ROOT / "plugins" / "router" / "skills" / "agency-router" / "SKILL.md"

# The blind prompt. Deliberately thin: it points at the shipped skill and gets
# out of the way. Any routing advice added here would be measuring THIS FILE
# rather than SKILL.md, which is the artifact consumers actually receive.
PROMPT_TEMPLATE = """\
You are helping route a task to the right specialist agent.

Read the skill at {skill} and follow it to pick the single best specialist for
the task below. Its index and agent files are in the same directory.

TASK
----
{task}

Reply with exactly two lines and nothing else:

AGENT: <the agent id you picked, or NONE if nothing fits>
QUERIES: <the search patterns you tried, comma-separated>

Pick the specialist whose expertise best fits the problem. If you genuinely
cannot find a good match, answer NONE -- a wrong pick is worse than an honest
miss, and NONE is scored as its own outcome rather than as a failure to try.
"""


def load_cases() -> list[dict]:
    return [json.loads(line)
            for line in CASES.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def tasks_digest(cases: list[dict], case_ids: list[str] | None = None) -> str:
    """sha256 over the QUESTIONS ASKED, not over the whole benchmark file.

    A pick is an answer to a task string. The blind prompt carries the task and
    nothing else -- never `expect`, never `why`, never `kind` -- so those fields
    cannot have influenced any recorded answer. Hashing the whole file therefore
    binds picks to data they never saw, and correcting one wrong expectation
    invalidates 58 answers that are all still valid.

    That is not hypothetical. The first full run surfaced three expectations
    authored from an agent's NAME rather than its description; under a
    whole-file hash the only way to score the correction was to re-run every
    case, which is a strong incentive to leave a known-wrong benchmark alone.
    A guard that makes the honest move expensive is a badly designed guard.

    So the digest covers sorted `(case id, task)` pairs for the cases a run
    actually answered:

      - editing a task      -> invalidates runs that answered it   (correct)
      - correcting `expect` -> leaves picks valid                  (the fix)
      - adding a case       -> earlier runs stay valid, merely partial, which
                               `cases_missing` already reports
      - deleting a case     -> invalidates runs that answered it, which the
                               ratchet on `cases.total` should prevent anyway

    It guards against silent re-attribution, not against a determined editor:
    anyone can recompute the value and paste it in. The point is that it cannot
    happen by accident, and that a deliberate change leaves a diff.
    """
    wanted = None if case_ids is None else set(case_ids)
    blob = "\n".join(
        f"{c['case']}\t{c['task']}"
        for c in sorted(cases, key=lambda c: c["case"])
        if wanted is None or c["case"] in wanted)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def prompt_for(case: dict) -> str:
    return PROMPT_TEMPLATE.format(
        skill=SKILL.relative_to(REPO_ROOT).as_posix(), task=case["task"])


def sample(cases: list[dict], n: int) -> list[dict]:
    """A deterministic stratified subset, for pilot runs.

    Round-robin across the divisions of the expected agents, taking cases in id
    order within each. No RNG, so `--sample 15` is the same 15 for anyone who
    runs it and the choice can be audited rather than trusted.

    The obvious alternative -- the first N cases -- is what this exists to
    avoid: case ids run in authoring order, so c001..c015 over-weights whichever
    divisions happened to get written first and would make a pilot's numbers a
    property of that accident.

    KNOWN BIAS, measured on the first run: round-robin puts at most one case per
    division until every division has one, so a small sample lands one case in
    each of N divisions and never makes two cases compete inside the same one.
    That removes within-division discrimination -- picking one of 58 engineering
    specialists -- which is the harder half of routing. A sample drawn this way
    is a fair breadth check and an EASY accuracy test; do not read a small
    sample's accuracy as an estimate of the full set's.
    """
    registry = json.loads((REPO_ROOT / "registry.json").read_bytes().decode("utf-8"))
    division_of = {a["id"]: a["division"] for a in registry["agents"]}

    buckets: dict[str, list[dict]] = {}
    for case in sorted(cases, key=lambda c: c["case"]):
        buckets.setdefault(division_of.get(case["expect"][0], "?"), []).append(case)

    picked: list[dict] = []
    depth = 0
    while len(picked) < n and any(len(b) > depth for b in buckets.values()):
        for division in sorted(buckets):
            if len(picked) >= n:
                break
            if len(buckets[division]) > depth:
                picked.append(buckets[division][depth])
        depth += 1
    return sorted(picked, key=lambda c: c["case"])


def load_runs(cases: list[dict]) -> list[dict]:
    """Every recorded run, oldest name first. Refuses picks that answer

    questions the benchmark no longer asks. See tasks_digest() for the exact
    binding; this is a hard error rather than a warning because the failure is
    otherwise invisible -- the accuracy number simply changes.
    """
    known = {c["case"] for c in cases}
    runs = []
    for path in sorted(RESPONSES.glob("*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        run = json.loads(path.read_bytes().decode("utf-8"))
        answered = [cid for cid in run.get("picks", {}) if cid in known]
        expected = tasks_digest(cases, answered)
        recorded = run.get("tasks_sha256")

        if recorded is None:
            raise SystemExit(
                f"{rel}: no `tasks_sha256`.\n"
                f"  This file predates the task-text digest. If its picks were "
                f"collected against the current task text, record:\n"
                f'    "tasks_sha256": "{expected}"\n'
                f"  If they were not, re-run the eval instead.")
        if recorded != expected:
            raise SystemExit(
                f"{rel}: the task text changed after these picks were "
                f"collected.\n"
                f"  recorded {recorded[:16]}\n"
                f"  current  {expected[:16]}\n"
                f"  These picks answer questions the benchmark no longer asks. "
                f"Re-run the eval, or restore the task text.\n"
                f"  Note: correcting `expect` or `why` does NOT trip this -- "
                f"only the task strings themselves do.")

        run["_name"] = path.stem
        runs.append(run)
    return runs


def agent_ids() -> set[str]:
    registry = json.loads(
        (REPO_ROOT / "registry.json").read_text(encoding="utf-8"))
    return {a["id"] for a in registry["agents"]}


def score_run(run: dict, cases: list[dict], reachable: dict[str, bool],
              known_ids: set[str]) -> dict:
    """One run scored against the cases, cross-tabbed with Phase 6 reachability."""
    picks = run["picks"]
    rows, missing = [], []
    # The four cells the accuracy number would otherwise blend together.
    cells = {"reachable_correct": [], "reachable_wrong": [],
             "translated": [], "compound_failure": []}

    for case in cases:
        cid = case["case"]
        if cid not in picks:
            missing.append(cid)
            continue
        pick = picks[cid]
        chosen = pick.get("agent")
        correct = chosen in case["expect"]
        reach = reachable.get(cid, False)

        if chosen in (None, "NONE"):
            cell = None  # an honest miss is not scored as a wrong pick
        elif correct:
            cell = "reachable_correct" if reach else "translated"
        else:
            cell = "reachable_wrong" if reach else "compound_failure"
        if cell:
            cells[cell].append(cid)

        rows.append({
            "case": cid, "expect": case["expect"], "picked": chosen,
            "correct": correct, "literally_reachable": reach,
            "queries": pick.get("queries", []),
        })

    # Effort, because correct/wrong hides a 3x spread in what a pick costs.
    # A case answered in 2 queries and one answered in 13 both score correct;
    # only one of them says the index found it quickly.
    effort = sorted(p["tool_calls"] for p in picks.values() if "tool_calls" in p)

    answered = [r for r in rows if r["picked"] not in (None, "NONE")]
    declined = [r["case"] for r in rows if r["picked"] in (None, "NONE")]
    # An id that does not exist is a different failure from picking the wrong
    # real agent, and the cross-tab above blends the two into `reachable_wrong`.
    # Reported rather than asserted: a hallucinated pick is a true fact about a
    # model on a day, and a test that failed on it would punish honest recording.
    invented = sorted(r["case"] for r in answered if r["picked"] not in known_ids)
    correct = [r for r in rows if r["correct"]]
    unreachable = [r for r in rows if not r["literally_reachable"]]
    unreachable_ok = [r for r in unreachable if r["correct"]]

    return {
        "run": run["_name"],
        "runner": run.get("runner"),
        "model": run.get("model"),
        "recorded_at": run.get("recorded_at"),
        "scope": run.get("scope", "full"),
        "cases_scored": len(rows),
        "cases_missing": missing,
        "accuracy_pct": round(100.0 * len(correct) / len(rows), 2) if rows else 0.0,
        "accuracy_when_answered_pct": round(
            100.0 * len(correct) / len(answered), 2) if answered else 0.0,
        "declined": declined,
        "picked_nonexistent_agent": invented,
        "effort_tool_calls": {
            "median": effort[len(effort) // 2] if effort else None,
            "min": effort[0] if effort else None,
            "max": effort[-1] if effort else None,
        },
        "outcome_cells": {k: sorted(v) for k, v in cells.items()},
        "translation": {
            "_note": ("The cell scripts/eval_routing.py cannot measure. These "
                      "cases share no word with the right agent's index line, "
                      "so a correct pick means the model translated the task "
                      "into the field's vocabulary before searching -- which is "
                      "exactly what the router skill instructs."),
            "unreachable_cases": len(unreachable),
            "recovered": len(unreachable_ok),
            "recovery_pct": round(
                100.0 * len(unreachable_ok) / len(unreachable), 2)
            if unreachable else 0.0,
        },
        "per_case": rows,
    }


def build_report() -> dict:
    cases = load_cases()
    runs = load_runs(cases)
    routing = er.build_report()
    unreachable = set(routing["literal_reachability"]["requires_expansion"])
    reachable = {c["case"]: c["case"] not in unreachable for c in cases}

    return {
        "_note": ("Generated by scripts/eval_selection.py from the committed "
                  "responses in eval/selection/responses/. Scoring is a pure "
                  "function of (cases, responses) -- no model is called here, "
                  "which is what lets CI verify it."),
        "cases": {"total": len(cases), "tasks_sha256": tasks_digest(cases)},
        "literal_reachability_pct": routing["literal_reachability"]["pct"],
        "runs": [score_run(r, cases, reachable, agent_ids()) for r in runs],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify metrics/selection-baseline.json is current")
    ap.add_argument("--prompt", metavar="CASE",
                    help="print the blind prompt for one case")
    ap.add_argument("--template", action="store_true",
                    help="print the prompt template")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="print a deterministic stratified subset of N case ids")
    ap.add_argument("--digest", nargs="*", metavar="CASE",
                    help="print the tasks_sha256 a run should record; with no "
                         "arguments, the value for a full run")
    args = ap.parse_args()

    if args.template:
        sys.stdout.write(PROMPT_TEMPLATE)
        return 0

    if args.digest is not None:
        print(tasks_digest(load_cases(), args.digest or None))
        return 0

    if args.sample:
        cases = load_cases()
        registry = json.loads(
            (REPO_ROOT / "registry.json").read_bytes().decode("utf-8"))
        division_of = {a["id"]: a["division"] for a in registry["agents"]}
        chosen = sample(cases, args.sample)
        for case in chosen:
            print(f"{case['case']}  {division_of.get(case['expect'][0], '?'):<18}"
                  f"{case['kind']:<13}{case['expect'][0]}")
        divisions = {division_of.get(c["expect"][0], "?") for c in chosen}
        print(f"\n{len(chosen)} cases across {len(divisions)} divisions")
        return 0

    if args.prompt:
        case = next((c for c in load_cases() if c["case"] == args.prompt), None)
        if case is None:
            print(f"No such case: {args.prompt}", file=sys.stderr)
            return 1
        sys.stdout.write(prompt_for(case))
        return 0

    RESPONSES.mkdir(parents=True, exist_ok=True)
    report = build_report()
    blob = dump_json(report)

    if args.check:
        if not report["runs"]:
            print("PASSED: no recorded runs yet; nothing to verify.")
            return 0
        if not BASELINE.exists() or BASELINE.read_bytes() != blob:
            print("FAILED: metrics/selection-baseline.json is stale.\n",
                  file=sys.stderr)
            print("Regenerate with ./scripts/eval_selection.py", file=sys.stderr)
            return 1
        print(f"PASSED: selection baseline current "
              f"({len(report['runs'])} run(s), {report['cases']['total']} cases).")
        return 0

    if not report["runs"]:
        print(f"No runs recorded in "
              f"{RESPONSES.relative_to(REPO_ROOT).as_posix()}/ yet.")
        print("\nCollect picks with a blind runner, then re-run this script.")
        print("See docs/selection-evaluation.md.")
        return 0

    BASELINE.write_bytes(blob)
    print(f"Cases: {report['cases']['total']}   "
          f"literal reachability: {report['literal_reachability_pct']}%\n")
    for r in report["runs"]:
        print(f"{r['run']}  [{r['runner']} / {r['model']} / {r['scope']}]")
        print(f"  scored {r['cases_scored']}   accuracy {r['accuracy_pct']}%   "
              f"declined {len(r['declined'])}")
        c = r["outcome_cells"]
        print(f"  reachable & correct {len(c['reachable_correct']):>3}   "
              f"reachable & wrong {len(c['reachable_wrong']):>3}")
        print(f"  translated          {len(c['translated']):>3}   "
              f"compound failure  {len(c['compound_failure']):>3}")
        t = r["translation"]
        print(f"  translation recovery: {t['recovered']}/{t['unreachable_cases']} "
              f"({t['recovery_pct']}%) of cases Phase 6 cannot reach")
        e = r["effort_tool_calls"]
        if e["median"] is not None:
            print(f"  tool calls per pick: median {e['median']}, "
                  f"range {e['min']}-{e['max']}")
        if r["picked_nonexistent_agent"]:
            print(f"  INVENTED AGENT IDS: "
                  f"{' '.join(r['picked_nonexistent_agent'])}")
        if r["cases_missing"]:
            print(f"  NOT ANSWERED: {' '.join(r['cases_missing'])}")
        print()

    print(f"Wrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
