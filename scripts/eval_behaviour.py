#!/usr/bin/env python3
"""eval_behaviour.py -- does the agent file make the answer better?

    ./scripts/eval_behaviour.py                      # score every recorded run
    ./scripts/eval_behaviour.py --check              # CI: fail if the baseline is stale
    ./scripts/eval_behaviour.py --prompt b001 --condition current
    ./scripts/eval_behaviour.py --conditions         # what each condition is
    ./scripts/eval_behaviour.py --digest             # the tasks_sha256 a run records

PHASE 7, AND THE FIRST THING HERE THAT IS NOT LEXICAL

Every gate built before this one measures text: does an id match a pattern, do
two descriptions share shingles, can a grep reach the right agent. None of them
can tell whether an agent's advice is any good, which the handoff calls the
central engineering problem.

This measures one narrow, checkable piece of that: given a task with a KNOWN
planted defect, does the answer find it -- and does the agent file change
whether it finds it.

THE THREE CONDITIONS ARE THE WHOLE DESIGN

    none       the task, and nothing else
    current    the task, plus the agent file as it ships today
    candidate  the task, plus a proposed replacement agent file

`none` is not a formality. It is the control. An agent file that scores the same
as no agent file at all is decoration, however well it reads, and no amount of
lexical validation would ever say so. The number that matters is therefore never
the score -- it is `current` minus `none`.

WHY PLANTED DEFECTS, AND NOT "GENERATE CODE AND RUN THE TESTS"

Running model-generated code would be rung 1 of the handoff's evidence hierarchy
too, but it costs two things this project is not willing to spend yet: scoring
would stop being a pure function of committed data (which is the only reason
Phase 8's `--check` runs free in CI), and public CI would be executing generated
code. A planted defect is checkable by matching alone: deterministic, free,
reviewable in a diff, and no sandbox.

The cost is honest to state: this measures DIAGNOSIS, not construction. An agent
that spots every bug and writes terrible code scores perfectly here.

RECALL ALONE IS A TRAP, SO PRECISION IS MEASURED WITH IT

An answer that lists twenty possible problems will hit the planted one by
accident. That is the same failure the routing harness has with OR-ing every
word: widen the query and the hit rate rises for free. So every task also names
`clean` aspects -- things deliberately CORRECT in the fixture -- and claiming
one is a false claim.

    found_pct     planted defects identified
    false_pct     deliberately-correct aspects claimed as broken
    lift          found_pct - false_pct

`lift` is the only figure comparable between conditions, for exactly the reason
`lift_over_control` is in scripts/eval_routing.py: padding the answer raises
both terms.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import REPO_ROOT, dump_json  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BEHAVIOUR = REPO_ROOT / "eval" / "behaviour"
TASKS = BEHAVIOUR / "tasks.jsonl"
FIXTURES = BEHAVIOUR / "fixtures"
RESPONSES = BEHAVIOUR / "responses"
BASELINE = REPO_ROOT / "metrics" / "behaviour-baseline.json"

CONDITIONS = {
    "none": "The task and the fixture, with no agent file. THE CONTROL -- an "
            "agent that cannot beat this is not earning its place.",
    "current": "The task, the fixture, and the agent file as it ships today.",
    "candidate": "The task, the fixture, and a proposed replacement agent file.",
    "flattened": "The task, the fixture, and a GENERIC agent file with the "
                 "specialist content stripped out. POSITIVE CONTROL -- if this "
                 "scores like `current`, the harness cannot see agent quality "
                 "and no result from it means anything.",
}

# Deliberately thin, and identical across conditions except for the agent file.
# Any diagnostic hint added here would be measured instead of the agent.
PROMPT_TEMPLATE = """\
{preamble}
TASK
----
{prompt}

FILE UNDER REVIEW: {fixture_name}
```
{fixture}
```

List every real problem you find. For each one give a single line:

FINDING: <one sentence naming the problem and where it is>

Then a final line:

DONE: <how many findings you reported>

Report only problems you are confident are real. Listing everything that might
conceivably be wrong is not thoroughness -- a claim about correct code is a
false claim, and is scored as one.
"""

PREAMBLE = {
    "none": "You are reviewing a file for a colleague.\n",
    "current": "You are reviewing a file for a colleague. Adopt the standards "
               "of the specialist described in {agent_path}, which you should "
               "read first.\n",
}
PREAMBLE["candidate"] = PREAMBLE["current"]
PREAMBLE["flattened"] = PREAMBLE["current"]

# The positive control's content. Deliberately the kind of text that reads like
# a competent specialist and says nothing a specialist would say -- the failure
# mode `archive/fable-upgrade` produced at scale, and the same construction the
# routing harness uses when it flattens all 270 descriptions.
FLATTENED_BODY = """\
You are an expert specialist. Apply rigorous professional judgment and industry
best practices to every task.

## Approach

- Understand the requirements thoroughly before proceeding.
- Apply proven patterns and established conventions.
- Consider correctness, maintainability, performance, and security.
- Communicate findings clearly and actionably.

## Standards

Deliver work that meets professional standards. Be thorough. Be precise. Focus
on outcomes that provide real value to stakeholders.
"""


def flattened_dir() -> Path:
    return FIXTURES / "flattened"


def flattened_text(agent_id: str) -> str:
    """The generic stand-in, built from the real file's frontmatter.

    Frontmatter is preserved so the ONLY difference from `current` is the
    specialist body. If the control kept nothing of the original, a score drop
    could just mean the model got a malformed file.
    """
    raw = (REPO_ROOT / agent_path(agent_id)).read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    frontmatter = parts[1] if len(parts) >= 3 else "\n"
    return f"---{frontmatter}---\n\n{FLATTENED_BODY}"


def load_tasks() -> list[dict]:
    return [json.loads(line)
            for line in TASKS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def tasks_digest(tasks: list[dict], task_ids: list[str] | None = None) -> str:
    """sha256 over the questions asked: task id, prompt, and fixture bytes.

    Same rule as scripts/eval_selection.py, and for the same reason -- a run is
    bound to what it was asked, not to the expected answers. Editing `planted`
    or `clean` after a run is a scoring change, and must not invalidate answers
    that are still answers to the same question. Editing the prompt or the
    fixture IS a different question, and must.
    """
    wanted = None if task_ids is None else set(task_ids)
    parts = []
    for t in sorted(tasks, key=lambda t: t["task"]):
        if wanted is not None and t["task"] not in wanted:
            continue
        fixture = (FIXTURES / t["fixture"]).read_bytes()
        parts.append(f"{t['task']}\t{t['prompt']}\t"
                     f"{hashlib.sha256(fixture).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def agent_path(agent_id: str) -> str:
    division = agent_id.split("-")[0]
    return f"{division}/{agent_id}.md"


def prompt_for(task: dict, condition: str) -> str:
    if condition not in CONDITIONS:
        raise KeyError(condition)
    fixture = (FIXTURES / task["fixture"]).read_text(encoding="utf-8")
    # The control must be delivered exactly as `current` is -- a file to read at
    # a path. Handing one condition a path and another inline text would confound
    # the comparison with the delivery mechanism.
    path = (flattened_dir() / f"{task['agent']}.md"
            ).relative_to(REPO_ROOT).as_posix() if condition == "flattened" \
        else agent_path(task["agent"])
    preamble = PREAMBLE[condition].format(agent_path=path)
    return PROMPT_TEMPLATE.format(
        preamble=preamble, prompt=task["prompt"],
        fixture_name=task["fixture"], fixture=fixture.rstrip("\n"))


def matched(answer: str, phrasings: list[str]) -> str | None:
    """The first phrasing present, case-insensitively.

    Matching is literal, not a model. Asking a judge whether a finding "counts"
    would put rung 4 evidence where rung 1 is supposed to be, and would make
    every score depend on a second model nobody calibrated. The cost is that
    phrasing lists are maintained by hand -- visible work rather than invisible
    drift.

    WORD BOUNDARIES, and why they are not optional. Plain substring matching
    scores `SQLi` inside `sqlite3`, so any answer that merely mentioned the
    import counted as having found a SQL injection. That was caught by
    test_no_planted_phrasing_appears_in_the_prompt_or_fixture before a single
    answer was collected, which is the only reason it is a footnote instead of
    a result.

    A boundary is required only at an end that is alphanumeric, so phrases like
    `.aggregate` and `key={index}` still match where a naive `\\b...\\b` would
    silently never fire -- the worse failure, because it looks like a clean miss.
    """
    low = answer.lower()
    for p in phrasings:
        needle = p.lower()
        left = r"\b" if needle[:1].isalnum() else ""
        right = r"\b" if needle[-1:].isalnum() else ""
        if re.search(left + re.escape(needle) + right, low):
            return p
    return None


def score_answer(task: dict, answer: str) -> dict:
    found, missed, false_claims = [], [], []
    for defect in task["planted"]:
        hit = matched(answer, defect["any_of"])
        (found if hit else missed).append(
            {"id": defect["id"], "matched": hit} if hit else {"id": defect["id"]})
    for clean in task["clean"]:
        hit = matched(answer, clean["any_of"])
        if hit:
            false_claims.append({"id": clean["id"], "matched": hit})

    claimed = len(re.findall(r"^\s*FINDING:", answer, re.MULTILINE))
    return {
        "task": task["task"],
        "agent": task["agent"],
        "planted_total": len(task["planted"]),
        "found": [f["id"] for f in found],
        "missed": [m["id"] for m in missed],
        "false_claims": [c["id"] for c in false_claims],
        "clean_total": len(task["clean"]),
        "findings_reported": claimed,
    }


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def score_condition(rows: list[dict]) -> dict:
    planted = sum(r["planted_total"] for r in rows)
    found = sum(len(r["found"]) for r in rows)
    clean = sum(r["clean_total"] for r in rows)
    false_ = sum(len(r["false_claims"]) for r in rows)
    found_pct, false_pct = pct(found, planted), pct(false_, clean)
    return {
        "tasks": len(rows),
        "found": found, "planted_total": planted, "found_pct": found_pct,
        "false_claims": false_, "clean_total": clean, "false_pct": false_pct,
        "lift": round(found_pct - false_pct, 2),
        "findings_reported": sum(r["findings_reported"] for r in rows),
        "per_task": rows,
    }


def load_runs(tasks: list[dict]) -> list[dict]:
    known = {t["task"] for t in tasks}
    runs = []
    for path in sorted(RESPONSES.glob("*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        run = json.loads(path.read_text(encoding="utf-8"))
        answered = sorted({tid for c in run.get("answers", {}).values()
                           for tid in c if tid in known})
        expected = tasks_digest(tasks, answered)
        recorded = run.get("tasks_sha256")
        if recorded != expected:
            raise SystemExit(
                f"{rel}: the prompt or fixture changed after these answers "
                f"were collected.\n  recorded {recorded or '(none)'}\n"
                f"  current  {expected}\n"
                f"  Re-run, or restore the task text. Editing `planted` or "
                f"`clean` does NOT trip this -- only prompts and fixtures do.")
        run["_name"] = path.stem
        runs.append(run)
    return runs


def build_report() -> dict:
    tasks = load_tasks()
    by_id = {t["task"]: t for t in tasks}
    runs = []
    for run in load_runs(tasks):
        conditions = {}
        for condition, answers in run["answers"].items():
            rows = [score_answer(by_id[tid], text)
                    for tid, text in sorted(answers.items()) if tid in by_id]
            conditions[condition] = score_condition(rows)

        base = conditions.get("none", {}).get("lift")
        deltas = {c: round(v["lift"] - base, 2)
                  for c, v in conditions.items() if base is not None}
        runs.append({
            "run": run["_name"], "runner": run.get("runner"),
            "model": run.get("model"), "recorded_at": run.get("recorded_at"),
            "conditions": conditions,
            "lift_over_no_skill": deltas,
            "_note": ("lift_over_no_skill is the only figure that answers the "
                      "question this phase exists for. A `current` value at or "
                      "below zero means the agent file changed nothing, "
                      "whatever its absolute score."),
        })

    return {
        "_note": ("Generated by scripts/eval_behaviour.py from the committed "
                  "answers in eval/behaviour/responses/. Scoring is a pure "
                  "function of (tasks, fixtures, answers) -- no model is "
                  "called here, which is what lets CI verify it."),
        "tasks": {"total": len(tasks), "tasks_sha256": tasks_digest(tasks)},
        "conditions": CONDITIONS,
        "runs": runs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prompt", metavar="TASK")
    ap.add_argument("--condition", default="current", choices=sorted(CONDITIONS))
    ap.add_argument("--conditions", action="store_true")
    ap.add_argument("--digest", nargs="*", metavar="TASK")
    ap.add_argument("--emit-controls", action="store_true",
                    help="regenerate the flattened positive-control files")
    args = ap.parse_args()

    if args.emit_controls:
        flattened_dir().mkdir(parents=True, exist_ok=True)
        for agent in sorted({t["agent"] for t in load_tasks()}):
            out = flattened_dir() / f"{agent}.md"
            out.write_text(flattened_text(agent), encoding="utf-8", newline="\n")
            print(f"wrote {out.relative_to(REPO_ROOT).as_posix()}")
        return 0

    if args.conditions:
        for name, why in CONDITIONS.items():
            print(f"{name:<11} {why}\n")
        return 0

    if args.digest is not None:
        print(tasks_digest(load_tasks(), args.digest or None))
        return 0

    if args.prompt:
        task = next((t for t in load_tasks() if t["task"] == args.prompt), None)
        if task is None:
            print(f"No such task: {args.prompt}", file=sys.stderr)
            return 1
        sys.stdout.write(prompt_for(task, args.condition))
        return 0

    RESPONSES.mkdir(parents=True, exist_ok=True)
    report = build_report()
    blob = dump_json(report)

    if args.check:
        if not report["runs"]:
            print("PASSED: no recorded runs yet; nothing to verify.")
            return 0
        if not BASELINE.exists() or BASELINE.read_bytes() != blob:
            print("FAILED: metrics/behaviour-baseline.json is stale.\n",
                  file=sys.stderr)
            print("Regenerate with ./scripts/eval_behaviour.py", file=sys.stderr)
            return 1
        print(f"PASSED: behaviour baseline current "
              f"({len(report['runs'])} run(s), {report['tasks']['total']} tasks).")
        return 0

    if not report["runs"]:
        print(f"Tasks: {report['tasks']['total']}   "
              f"digest: {report['tasks']['tasks_sha256'][:16]}")
        print(f"\nNo runs recorded in "
              f"{RESPONSES.relative_to(REPO_ROOT).as_posix()}/ yet.")
        print("Generate a prompt with --prompt <task> --condition <condition>, "
              "collect answers blind, then re-run this script.")
        print("See docs/behaviour-evaluation.md.")
        return 0

    BASELINE.write_bytes(blob)
    print(f"Tasks: {report['tasks']['total']}\n")
    for r in report["runs"]:
        print(f"{r['run']}  [{r['runner']} / {r['model']}]")
        print(f"  {'condition':<11}{'found':>12}{'false':>12}{'lift':>9}"
              f"{'vs none':>9}")
        for cond in ("none", "current", "candidate", "flattened"):
            c = r["conditions"].get(cond)
            if not c:
                continue
            delta = r["lift_over_no_skill"].get(cond)
            print(f"  {cond:<11}"
                  f"{c['found']}/{c['planted_total']} ({c['found_pct']}%)".rjust(12)
                  + f"{c['false_claims']}/{c['clean_total']} ({c['false_pct']}%)".rjust(12)
                  + f"{c['lift']:>9}"
                  + (f"{delta:>+9}" if delta is not None and cond != "none" else " " * 9))
        print()

    print(f"Wrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
