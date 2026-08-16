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

THE ORACLE IS A LINE NUMBER, AFTER PROSE MATCHING FAILED

Findings are scored by WHERE they point, not by how they are worded. A planted
defect is found when the answer cites a line inside its range.

The first version matched prose against hand-written phrasing lists, and the
2026-08-16 pilot invalidated it outright: the generic positive control beat the
real agent by 25 points because it happened to write "two queries per customer"
where the real agent wrote "evaluates the same orders queryset twice". Same
diagnosis, 3/3 against 1/3. Widening the lists to fit answers already collected
would be fitting the key to the data, so the oracle was replaced instead.

Line numbers are unambiguous, need no phrasing list, and leak nothing -- the
answerer still has to find the line. A finding with no `L<n>` is unscoreable and
is counted as such, so contract failures are visible rather than silently
scored as misses.

PRECISION IS NOT SCORED, AND THAT IS A DELIBERATE RETREAT

The first version scored `clean` aspects -- code asserted to be correct, where a
claim was a false claim. Two things killed it. It never fired once across 12
answers, so `lift = found - false` was plain recall in disguise. And the pilot
found FOUR real defects in code the key had asserted was clean, two of them
inside `clean` aspects.

That second one generalises: the author of a fixture does not reliably know
what is wrong with it. Any precision measure built on a complete defect
inventory inherits that, and a precision measure that punishes an answer for
being right about an unlisted defect is worse than none.

So what is reported instead is COST, not correctness:

    recall_pct       planted defects whose line was cited
    lines_cited      distinct lines the answer points at
    defect_density   found / lines_cited -- a scattergun answer scores badly
    contract_pct     findings carrying a line, over findings declared

`defect_density` makes padding visible without claiming the extra citations are
wrong. Read it the way `effort_tool_calls` is read in the selection harness.
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
Line numbers are shown for reference and are not part of the file.
```
{fixture}
```

For every real problem you find, give one line in exactly this form:

FINDING: L<line>: <one sentence naming the problem>

<line> is the single line number where the problem lives. Give the most
specific line, not a range. Then a final line:

DONE: <how many findings you reported>

Report only problems you are confident are real. Every line you cite is
counted, so an answer that points at many lines to be safe is a worse answer,
not a more thorough one.
"""

# The scoring contract. A finding must carry a line, or it does not exist as
# far as this harness is concerned -- see score_answer() for why that is a
# deliberate hard edge rather than a leniency worth adding.
FINDING_RE = re.compile(r"^[^\S\n]*FINDING:\s*L(\d+)\s*:", re.MULTILINE)

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
    # PROMPT_TEMPLATE is part of the question, and leaving it out was a real
    # defect: the 2026-08-16 pilot was answered under a template that never
    # asked for line numbers, and a digest blind to that would have let those
    # answers be silently re-scored by an oracle they could not satisfy. Nine of
    # the twelve would have scored zero, and the zero would have looked like a
    # measurement.
    parts = [hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()]
    for t in sorted(tasks, key=lambda t: t["task"]):
        if wanted is not None and t["task"] not in wanted:
            continue
        fixture = (FIXTURES / t["fixture"]).read_bytes()
        parts.append(f"{t['task']}\t{t['prompt']}\t"
                     f"{hashlib.sha256(fixture).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def numbered(task: dict) -> str:
    """The fixture with line numbers, so a citation costs no counting.

    Without this the answerer has to count lines by hand, and a miscount would
    be scored as a wrong diagnosis. The numbers leak nothing -- every line gets
    one.
    """
    body = (FIXTURES / task["fixture"]).read_text(encoding="utf-8").rstrip("\n")
    return "\n".join(f"{i:>4}  {line}"
                     for i, line in enumerate(body.splitlines(), 1))


def agent_path(agent_id: str) -> str:
    division = agent_id.split("-")[0]
    return f"{division}/{agent_id}.md"


def prompt_for(task: dict, condition: str) -> str:
    if condition not in CONDITIONS:
        raise KeyError(condition)
    fixture = numbered(task)
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


def findings(answer: str) -> list[int]:
    """The line each FINDING points at, in order, NOT deduplicated.

    Deduplicating was wrong. `b004/none` filed two distinct findings at L21 --
    a TOCTOU race and a rows-vs-seats miscount -- and collapsing them to one
    line makes it impossible for both to be credited. Duplicates are kept here
    and deduplicated only for `lines_cited`, which is a breadth-of-claim
    measure where counting the same line twice would be misleading.
    """
    return [int(m.group(1)) for m in FINDING_RE.finditer(answer)]


def assign(lines: list[int], planted: list[dict]) -> dict[str, int]:
    """Maximum matching of findings to defects. One finding, one defect.

    WHY NOT INDEPENDENT MATCHING. Checking each defect against the whole set of
    cited lines lets a single vague finding score every defect whose window it
    touches. Windows must overlap here -- `b004`'s race and its rows-vs-seats
    miscount both centre on L21 -- so independent matching would over-credit
    exactly where the fixture is most subtle.

    Matching gives the honest reading in both directions: two findings on the
    same line can be credited with two defects, and one finding on that line
    can be credited with only one. Sizes are tiny (<= 5 defects, <= 12
    findings), so a plain augmenting-path search is more than fast enough.

    Returns {defect id: index into `lines`}.
    """
    cand = {d["id"]: [i for i, n in enumerate(lines)
                      if d["lines"][0] - d.get("window", 1) <= n
                      <= d["lines"][1] + d.get("window", 1)]
            for d in planted}

    taken: dict[int, str] = {}

    def augment(did: str, seen: set[int]) -> bool:
        for i in cand[did]:
            if i in seen:
                continue
            seen.add(i)
            if i not in taken or augment(taken[i], seen):
                taken[i] = did
                return True
        return False

    for d in planted:
        augment(d["id"], set())
    return {did: i for i, did in taken.items()}


def score_answer(task: dict, answer: str) -> dict:
    """Recall by line citation, within a per-defect window.

    The window exists because the 2026-08-16 v2 pilot scored three correct
    diagnoses as misses purely on attribution: a reviewer put the race at the
    line where the count is taken rather than where it is compared, and folded
    two adjacent defects into one finding. The key's granularity and a human's
    are different things, and the key is the one that has to give.
    """
    lines = findings(answer)
    matched = assign(lines, task["planted"])
    found = [d["id"] for d in task["planted"] if d["id"] in matched]
    missed = [d["id"] for d in task["planted"] if d["id"] not in matched]

    declared = re.search(r"(?m)^[ 	]*DONE:[ 	]*(\d+)", answer)
    return {
        "task": task["task"],
        "agent": task["agent"],
        "planted_total": len(task["planted"]),
        "found": found,
        "missed": missed,
        "lines_cited": sorted(set(lines)),
        "findings_with_a_line": len(lines),
        "findings_declared": int(declared.group(1)) if declared else None,
    }


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def score_condition(rows: list[dict]) -> dict:
    planted = sum(r["planted_total"] for r in rows)
    found = sum(len(r["found"]) for r in rows)
    cited = sum(len(r["lines_cited"]) for r in rows)
    declared = sum(r["findings_declared"] or 0 for r in rows)
    with_line = sum(r["findings_with_a_line"] for r in rows)
    return {
        "tasks": len(rows),
        "found": found,
        "planted_total": planted,
        "recall_pct": pct(found, planted),
        # COST, not precision. A scattergun answer citing every line scores full
        # recall and terrible density. This does NOT claim the extra citations
        # are wrong -- the pilot found four real defects the answer key had
        # missed, so treating unlisted citations as errors would punish being
        # right. Read it as breadth-of-claim, the way effort_tool_calls is read
        # in the selection harness.
        "lines_cited": cited,
        "defect_density": round(found / cited, 3) if cited else 0.0,
        # Contract compliance. Findings without an L<n> prefix are unscoreable,
        # so a gap between these two numbers means the run measured less than it
        # appears to.
        "findings_with_a_line": with_line,
        "findings_declared": declared,
        "contract_pct": pct(with_line, declared) if declared else 0.0,
        "per_task": rows,
    }


def load_runs(tasks: list[dict]) -> list[dict]:
    known = {t["task"] for t in tasks}
    runs, superseded = [], []
    for path in sorted(RESPONSES.glob("*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        run = json.loads(path.read_text(encoding="utf-8"))

        # A run answered under an older protocol is evidence, not an error, and
        # not something to delete. It is skipped with its reason surfaced in the
        # report rather than silently dropped or force-fitted to an oracle it
        # could not have satisfied. The field is explicit and requires a written
        # reason precisely so it cannot become a quiet way to discard an
        # inconvenient result.
        if run.get("superseded"):
            superseded.append({"run": path.stem, "reason": run["superseded"],
                               "protocol": run.get("protocol")})
            continue

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
    return runs, superseded


def build_report() -> dict:
    tasks = load_tasks()
    by_id = {t["task"]: t for t in tasks}
    runs = []
    scored, superseded = load_runs(tasks)
    for run in scored:
        conditions = {}
        for condition, answers in run["answers"].items():
            rows = [score_answer(by_id[tid], text)
                    for tid, text in sorted(answers.items()) if tid in by_id]
            conditions[condition] = score_condition(rows)

        base = conditions.get("none", {}).get("recall_pct")
        deltas = {c: round(v["recall_pct"] - base, 2)
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
        "superseded_runs": superseded,
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
        for sup in report["superseded_runs"]:
            print(f"\n  SUPERSEDED  {sup['run']}  (protocol {sup['protocol']})")
            print(f"    {sup['reason']}")
        print(f"\nNo scoreable runs in "
              f"{RESPONSES.relative_to(REPO_ROOT).as_posix()}/ yet.")
        print("Generate a prompt with --prompt <task> --condition <condition>, "
              "collect answers blind, then re-run this script.")
        print("See docs/behaviour-evaluation.md.")
        return 0

    BASELINE.write_bytes(blob)
    print(f"Tasks: {report['tasks']['total']}\n")
    for r in report["runs"]:
        print(f"{r['run']}  [{r['runner']} / {r['model']}]")
        print(f"  {'condition':<11}{'recall':>14}{'lines':>7}{'density':>9}"
              f"{'contract':>10}{'vs none':>9}")
        for cond in ("none", "current", "candidate", "flattened"):
            c = r["conditions"].get(cond)
            if not c:
                continue
            delta = r["lift_over_no_skill"].get(cond)
            print(f"  {cond:<11}"
                  + f"{c['found']}/{c['planted_total']} ({c['recall_pct']}%)".rjust(14)
                  + f"{c['lines_cited']:>7}"
                  + f"{c['defect_density']:>9}"
                  + f"{c['contract_pct']:>9}%"
                  + (f"{delta:>+9}" if delta is not None and cond != "none" else " " * 9))
        print()

    print(f"Wrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
