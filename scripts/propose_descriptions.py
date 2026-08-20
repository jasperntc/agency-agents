#!/usr/bin/env python3
"""propose_descriptions.py -- would this description change actually help?

    ./scripts/propose_descriptions.py                  # score every proposal
    ./scripts/propose_descriptions.py --check          # CI: pure, no model
    ./scripts/propose_descriptions.py --calibrate      # the gate must reject bad ones
    ./scripts/propose_descriptions.py --show p001      # one proposal in detail

WHY THIS EXISTS, AND WHY IT POINTS AT DESCRIPTIONS RATHER THAN BODIES

Three axes have now been measured on two model tiers each:

    selection    WORKS. 57/58, and literal reachability 70.18% -- a third of
                 realistic tasks share no word with the right agent's index
                 line, which is measurable headroom.
    diagnosis    no measurable effect. 72 blind subagents. `none` scores the
                 same on Opus and Sonnet.
    construction at ceiling on both tiers. 44 blind subagents. `none` has never
                 once dropped below 100% on the implied checks.

So a loop that proposes improvements to agent BODIES would be optimising
against instruments that have never detected anything. A loop that proposes
improvements to DESCRIPTIONS is optimising against the one instrument in this
repository that demonstrably works, on the one axis with demonstrated headroom.
That is the whole argument for this file's existence, and if the evidence ever
turns the other way this file should be pointed somewhere else.

WHAT A PROPOSAL IS, AND WHAT IT IS NOT

A proposal is a suggested replacement for ONE agent's frontmatter description,
recorded in eval/proposals/descriptions.jsonl together with what prompted it.
Nothing here edits an agent file. The script scores; a human applies. That
separation is deliberate: an automatic rewriter would produce unproven content
faster, which is the failure mode this whole repository exists to avoid.

THE GATE IS NOT "DOES IT REACH ITS OWN CASE"

Widening a description until it matches its own test case is trivial and
worthless -- a description of every keyword in the corpus reaches everything.
The real problem a description has to solve is beating **269 competitors**, so
the gate scores both sides:

    gained      target cases that go UNREACHABLE -> REACHABLE. The point.
    lost        any case, anywhere, that was reachable and no longer is.
    attracted   OTHER cases -- ones this agent is NOT the answer to -- whose
                task now reaches it when it did not before. This is the cost of
                widening, counted in the same unit as the gain.

    ACCEPT  iff gained > 0 AND lost == 0 AND len(attracted) <= len(gained).

The exchange rule is deliberately plain: a description may start competing for
at most as many cases as it wins. There is no tuned threshold, because a tuned
threshold is how a gate gets fitted to the proposals it is meant to judge.

THE FIRST VERSION OF THIS GATE FAILED ITS OWN CALIBRATION, WHICH IS WHY IT SAYS
WHAT IT SAYS NOW

`attracted` originally counted PHRASE queries only, on the reasoning that
adjacent content-word phrases are what a person would really grep for. Both
keyword-stuffed calibration proposals sailed straight through: stuffing
single topic words into a description does not create adjacent-phrase
collisions, so the measure could not see the exact failure mode it existed to
catch. Counting distinct CASES reached, over singles and phrases alike, does
see it -- and the numbers separate cleanly:

    p001  wins 1 case, starts competing for 1     -> ACCEPT
    p002  wins 1, competes for 2                  -> REJECT
    p003  wins 1, competes for 4                  -> REJECT
    g001  wins 1, competes for 7                  -> REJECT (calibration)
    g002  wins 1, competes for 6                  -> REJECT (calibration)

Two of the three real proposals fail. That is the gate working, not the
proposals being badly written: **widening a description to reach one more task
usually costs more than one task in new competition.** That is the substantive
finding here, and it is the reason a description-tuning loop needs a gate at
all rather than a plausible-sounding rewrite.

The honest limit: appearing in a candidate set is not the same as being
picked. Selection sits at 57/58, so the router discriminates well among
candidates, and `attracted` therefore overstates real harm to some unknown
degree. It is a proxy for competitive pressure, chosen because it is
deterministic and free; a proposal it rejects is not proven harmful, only
unproven.

CALIBRATION, BECAUSE A GATE THAT ONLY EVER SAYS YES IS NOT A GATE

eval/proposals/calibration.jsonl holds proposals that are deliberately bad in
the specific way a keyword-stuffing rewriter fails: they reach their target and
grab half the corpus on the way. --calibrate asserts every one is REJECTED. If
that ever passes them, the gate has stopped measuring and no acceptance from it
means anything. Same two-sided rule as every other instrument here.

WHY THIS RUNS FREE IN CI

Reachability is literal grep over the index, computed by eval_routing.py with
no model in the loop. Scoring a proposal is therefore a pure function of
committed data -- the index, the cases, the proposals file -- and reproducible
forever. No model is called here, ever.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_routing as er  # noqa: E402
from lib.corpus import REPO_ROOT, dump_json  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PROPOSALS = REPO_ROOT / "eval" / "proposals" / "descriptions.jsonl"
CALIBRATION = REPO_ROOT / "eval" / "proposals" / "calibration.jsonl"
BASELINE = REPO_ROOT / "metrics" / "proposal-baseline.json"

SOURCES = {
    "measured-gap": "A case eval_routing reports as literally unreachable.",
    "session-correction": "A correction observed while actually working -- the "
                          "router picked wrong, or needed steering, and the "
                          "description is why.",
}


def load_proposals(path: Path = PROPOSALS) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def swap(entries: list[dict], agent_id: str, description: str) -> list[dict]:
    """The index as it would be with one description replaced.

    Rebuilds the `line` too, because reachability greps the whole line -- id,
    division, name and description -- and scoring the description in isolation
    would measure something the consumer never sees.
    """
    out = []
    for e in entries:
        if e["id"] != agent_id:
            out.append(e)
            continue
        line = " | ".join([e["id"], e["division"], e["name"], description])
        out.append({**e, "description": description, "line": line})
    return out


def reachable_ids(task: str, entries: list[dict], expect: list[str]) -> bool:
    """Is any expected agent reachable by a literal query drawn from the task?"""
    singles, phrases = er.candidates(task)
    for q in phrases + [re.escape(w) for w in singles]:
        if any(a in er.matches(q, entries) for a in expect):
            return True
    return False


def reaches(task: str, entries: list[dict], agent_id: str) -> bool:
    """Does any literal query drawn from this task reach this agent at all?

    Singles AND phrases. Counting phrases alone let keyword-stuffed
    descriptions through calibration -- see the module docstring.
    """
    singles, phrases = er.candidates(task)
    for q in phrases + [re.escape(w) for w in singles]:
        if agent_id in er.matches(q, entries):
            return True
    return False


def score(proposal: dict, entries: list[dict], cases: list[dict]) -> dict:
    agent = proposal["agent"]
    after = swap(entries, agent, proposal["proposed"])

    gained, lost, attracted = [], [], []
    for case in cases:
        expect = case.get("expect") or []
        task = case["task"]
        if expect:
            before_ok = reachable_ids(task, entries, expect)
            after_ok = reachable_ids(task, after, expect)
            if after_ok and not before_ok:
                gained.append(case["case"])
            elif before_ok and not after_ok:
                lost.append(case["case"])

        if agent in expect:
            continue
        # A case this agent is NOT the answer to. Newly reaching it means the
        # description has started competing for someone else's task.
        if reaches(task, after, agent) and not reaches(task, entries, agent):
            attracted.append(case["case"])

    verdict = ("ACCEPT" if gained and not lost
               and len(attracted) <= len(gained) else "REJECT")
    reasons = []
    if not gained:
        reasons.append("reaches no case it did not already reach")
    if lost:
        reasons.append(f"breaks reachability for {', '.join(lost)}")
    if len(attracted) > len(gained):
        reasons.append(f"wins {len(gained)} case(s) and starts competing for "
                       f"{len(attracted)}: {', '.join(attracted)}")
    elif attracted:
        reasons.append(f"also starts competing for {', '.join(attracted)} "
                       f"(within the {len(gained)} it wins)")

    return {
        "id": proposal["id"],
        "agent": agent,
        "targets": proposal.get("targets", []),
        "source": proposal.get("source"),
        "verdict": verdict,
        "gained": gained,
        "lost": lost,
        "attracted": attracted,
        "reasons": reasons,
    }


def build_report(path: Path = PROPOSALS) -> dict:
    entries = er.load_index()
    cases = er.load_cases()
    results = [score(p, entries, cases) for p in load_proposals(path)]
    return {
        "_note": ("Generated by scripts/propose_descriptions.py. Scoring is a "
                  "pure function of the committed index, cases and proposals "
                  "-- no model is called, which is what lets CI verify it. "
                  "ACCEPT means the change is worth making, not that it has "
                  "been made; nothing here edits an agent file."),
        "corpus": {
            "agents": len(entries),
            "cases": len(cases),
            "literal_reachability_pct":
                er.build_report()["literal_reachability"]["pct"],
        },
        "proposals": results,
        "summary": {
            "total": len(results),
            "accepted": sum(1 for r in results if r["verdict"] == "ACCEPT"),
            "rejected": sum(1 for r in results if r["verdict"] == "REJECT"),
        },
    }


def render(report: dict) -> None:
    c = report["corpus"]
    print(f"{c['agents']} agents, {c['cases']} cases, "
          f"literal reachability {c['literal_reachability_pct']}%\n")
    if not report["proposals"]:
        print("No proposals recorded yet. Append to "
              f"{PROPOSALS.relative_to(REPO_ROOT).as_posix()}.")
        return
    for r in report["proposals"]:
        mark = "PASS" if r["verdict"] == "ACCEPT" else "FAIL"
        print(f"  [{mark}] {r['id']}  {r['agent']}")
        print(f"         targets {', '.join(r['targets']) or '-'}"
              f"   gained {', '.join(r['gained']) or '-'}")
        for reason in r["reasons"]:
            print(f"         - {reason}")
    s = report["summary"]
    print(f"\n{s['accepted']} accepted, {s['rejected']} rejected, "
          f"{s['total']} scored.")


def calibrate() -> int:
    """Every deliberately-bad proposal must be REJECTED."""
    report = build_report(CALIBRATION)
    if not report["proposals"]:
        print("FAILED: no calibration proposals. The gate is unverified.",
              file=sys.stderr)
        return 1
    passed_through = [r for r in report["proposals"] if r["verdict"] == "ACCEPT"]
    for r in report["proposals"]:
        mark = "rejected" if r["verdict"] == "REJECT" else "ACCEPTED"
        print(f"  {r['id']}  {r['agent']}  {mark}")
        for reason in r["reasons"]:
            print(f"      - {reason}")
    if passed_through:
        print(f"\nFAILED: the gate accepted {len(passed_through)} proposal(s) "
              f"written to be unacceptable. It is no longer measuring "
              f"anything, and no ACCEPT from it means anything either.",
              file=sys.stderr)
        return 1
    print(f"\nPASSED: all {len(report['proposals'])} bad proposals rejected. "
          f"The gate can say no.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify metrics/proposal-baseline.json is current")
    ap.add_argument("--calibrate", action="store_true",
                    help="assert the gate rejects deliberately bad proposals")
    ap.add_argument("--show", metavar="ID", help="one proposal, in full")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.calibrate:
        return calibrate()

    if args.show:
        proposals = {p["id"]: p for p in load_proposals()}
        p = proposals.get(args.show)
        if p is None:
            print(f"No such proposal: {args.show}", file=sys.stderr)
            return 1
        entries = er.load_index()
        current = next((e["description"] for e in entries
                        if e["id"] == p["agent"]), "(agent not in index)")
        print(f"{p['id']}  {p['agent']}  [{p.get('source')}]")
        print(f"\n  observed: {p.get('observed', '')}")
        print(f"\n  current : {current}")
        print(f"\n  proposed: {p['proposed']}")
        print()
        print(json.dumps(score(p, entries, er.load_cases()), indent=2))
        return 0

    report = build_report()
    blob = dump_json(report)

    if args.check:
        if not BASELINE.exists() or BASELINE.read_bytes() != blob:
            print("FAILED: metrics/proposal-baseline.json is stale.\n"
                  "Regenerate with ./scripts/propose_descriptions.py",
                  file=sys.stderr)
            return 1
        print(f"PASSED: proposal baseline current "
              f"({report['summary']['total']} proposal(s)).")
        return 0

    if args.json:
        sys.stdout.write(blob.decode("utf-8"))
        return 0

    render(report)
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_bytes(blob)
    print(f"\nWrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
