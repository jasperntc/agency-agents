#!/usr/bin/env python3
"""eval_construction.py -- does the agent file make the CODE better?

    ./scripts/eval_construction.py                       # score every run
    ./scripts/eval_construction.py --check               # CI: pure, no execution
    ./scripts/eval_construction.py --prompt c001 --condition current --run RUN
    ./scripts/eval_construction.py --self-test           # suites vs references
    ./scripts/eval_construction.py --execute RUN         # LOCAL ONLY: runs code
    ./scripts/eval_construction.py --conditions | --checks | --digest

WHY THIS PHASE EXISTS

Phase 7 measured diagnosis: given a file with a known defect, does the answer
find it, and does the agent file change whether it finds it. Across 36 blind
subagents, 12 tasks and 40 planted defects it found nothing -- `none`,
`current` and `flattened` all landed on 37/40, and on the niche tier the
no-agent control scored 100%.

That is a real result about a real axis, and it is also a narrow one. An agent
that spots every bug and writes terrible code scores perfectly there. This
phase asks the other half of the question, which is the half the corpus is
actually for: BUILD THIS. Not "what is wrong with this".

STATED AND IMPLIED, AND WHY THE SPLIT IS THE WHOLE INSTRUMENT

Each task is a brief plus an acceptance suite the answerer never sees. Every
check in the suite is classified once, when it is written:

    stated    the brief says it. This is the FLOOR.
    implied   a competent practitioner in that domain meets it unasked.

If the brief spells out every requirement, all three conditions pass and the
experiment measures nothing -- which is exactly how a construction test fails
silently. So the discriminator is `implied`: keyset pagination that survives an
insert, a merge that is idempotent under replay, a pseudonym that is not a
base64 encoding, the Slavic teen exception. Nothing in any brief hints at any
of them.

`stated` is not decoration either. It is the sanity check that makes the
`implied` number readable at all: if the stated rate is not near ceiling in
every condition, the answers are bad for reasons that have nothing to do with
the agent file, and no implied comparison from that run means anything.

The two rates are never blended into one score. Same rule as every other
metric here.

THE CONTROLS ARE THE SAME TWO, FOR THE SAME TWO REASONS

    none        the brief, and nothing else. An agent file that does not beat
                this is decoration, however well it reads.
    flattened   a GENERIC agent file, real frontmatter, specialist body
                stripped. If this scores like `current`, the instrument cannot
                see agent quality and no result from it means anything.

`flattened` is delivered exactly as `current` is -- a file to read at a path.
Handing one condition a path and another inline text would measure the delivery
mechanism.

WHERE GENERATED CODE RUNS, WHICH HAD TO BE SETTLED BEFORE ANY OF THIS

Phase 7 chose planted defects partly to avoid this question. Answering it here:

    --execute   LOCAL and opt-in. One subprocess per artifact, isolated mode,
                a scratch working directory, a wall-clock timeout. It writes
                eval/construction/results/<run>.json, which records each
                check's outcome together with the sha256 of the artifact it
                ran and the sha256 of the suite it ran.

    --check     CI. Reads those committed results, re-verifies that both
                digests still match the committed bytes, and re-scores. It
                never imports an artifact.

So scoring stays a pure function of committed data, which is the only reason
--check runs free, and public CI never executes generated code. The honest
limit: --check proves the recorded results belong to THESE bytes, not that
re-running would reproduce them. Reproducing them is what --execute is for,
and it costs seconds because no model is called.

THE ANSWER KEY IS THE SUITE, SO THE SUITE WAS NOT IN THE REPOSITORY

An answerer with repository access can read anything committed. tasks.jsonl
therefore carries the QUESTION only -- id, agent, module name, brief. Every
requirement, and the word "implied" itself, lives in eval/construction/suites/,
which was written first, kept outside the working tree while the answers were
collected, and moved in afterwards. tasks.jsonl records each suite's sha256 as
of registration so that pre-registration is checkable rather than merely
claimed, and the report discloses any suite that no longer matches it.

Amending a suite is allowed and visible. Locking it would force a broken check
to stay broken, which is worse -- the Phase 7 oracle was rebuilt twice and both
rebuilds were right.

THE REFERENCES EXIST BECAUSE THE AUTHOR OF A FIXTURE DOES NOT KNOW WHAT IS
WRONG WITH IT

Phase 7's pilot found four real defects in code its own answer key asserted was
clean. The same hand wrote these suites. So every task also has a reference
implementation, and --self-test runs every suite against it: a check a
competent implementation fails is a broken check, and this is the only way to
learn that before the run rather than from the results. tests/ asserts it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_behaviour import FLATTENED_BODY  # noqa: E402
from lib.corpus import REPO_ROOT, dump_json  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CONSTRUCTION = REPO_ROOT / "eval" / "construction"
TASKS = CONSTRUCTION / "tasks.jsonl"
SUITES = CONSTRUCTION / "suites"
REFERENCE = CONSTRUCTION / "reference"
NAIVE = CONSTRUCTION / "naive"
ARTIFACTS = CONSTRUCTION / "artifacts"
RESULTS = CONSTRUCTION / "results"
CONTROLS = CONSTRUCTION / "flattened"
RUNNER = REPO_ROOT / "scripts" / "lib" / "run_suite.py"
BASELINE = REPO_ROOT / "metrics" / "construction-baseline.json"

EXECUTE_TIMEOUT = 120  # seconds per artifact, wall clock

CONDITIONS = {
    "none": "The brief, with no agent file. THE CONTROL -- an agent that "
            "cannot beat this is not earning its place.",
    "current": "The brief, plus the agent file as it ships today.",
    "candidate": "The brief, plus a proposed replacement agent file.",
    "flattened": "The brief, plus a GENERIC agent file with the specialist "
                 "content stripped out. POSITIVE CONTROL -- if this scores "
                 "like `current`, the harness cannot see agent quality and no "
                 "result from it means anything.",
}

KINDS = ("stated", "implied")

# Identical across conditions except for the agent file. Any hint about what is
# graded would be measured instead of the agent -- and a hint here would leak
# the implied requirements, which is the one thing that would void the phase.
PROMPT_TEMPLATE = """\
{preamble}
BRIEF
-----
{brief}

Write the complete module and save it to exactly this path:

    {out_path}

Rules:
  - Python standard library only. No third-party imports.
  - Write that one file and nothing else. No tests, no notes, no example
    scripts, and do not modify any other file in the repository.
  - The module must import cleanly on its own.

Reply with a one-line confirmation of the path you wrote. Nothing else.
"""

PREAMBLE = {
    "none": "You are writing a module for a colleague.\n",
    "current": "You are writing a module for a colleague. Adopt the standards "
               "of the specialist described in {agent_path}, which you should "
               "read first.\n",
}
PREAMBLE["candidate"] = PREAMBLE["current"]
PREAMBLE["flattened"] = PREAMBLE["current"]


# --------------------------------------------------------------------------
# tasks, digests, paths


def load_tasks() -> list[dict]:
    return [json.loads(line)
            for line in TASKS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def tasks_digest(tasks: list[dict], task_ids: list[str] | None = None) -> str:
    """sha256 over the questions asked. NEVER over the acceptance suites.

    Same rule as eval_behaviour.py and eval_selection.py. A run is bound to
    what it was asked, not to how it is graded -- so a suite can be corrected
    without invalidating answers that are still answers to the same question,
    and changing a brief invalidates them properly.

    PROMPT_TEMPLATE is part of the question. Leaving it out was a real defect
    in the behaviour harness and it is not repeated here.
    """
    wanted = None if task_ids is None else set(task_ids)
    parts = [hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()]
    for t in sorted(tasks, key=lambda t: t["task"]):
        if wanted is not None and t["task"] not in wanted:
            continue
        # A starter file would be part of the question too. None of the six
        # tasks has one today; the hook is here so that adding one cannot
        # silently escape the digest.
        starter = t.get("starter")
        starter_hash = "-" if not starter else hashlib.sha256(
            (CONSTRUCTION / starter).read_bytes()).hexdigest()
        parts.append(f"{t['task']}\t{t['module']}\t{t['brief']}\t{starter_hash}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_path(agent_id: str) -> str:
    return f"{agent_id.split('-')[0]}/{agent_id}.md"


def suite_path(task: dict, suites: Path) -> Path:
    return suites / f"{task['task']}.py"


def artifact_path(run: str, condition: str, task: dict) -> Path:
    return ARTIFACTS / run / condition / task["module"]


def flattened_text(agent_id: str) -> str:
    """The generic stand-in, built from the real file's frontmatter.

    Frontmatter is kept so the ONLY difference from `current` is the specialist
    body -- otherwise a score drop could just mean the model got a malformed
    file. FLATTENED_BODY is imported from the behaviour harness rather than
    copied so the positive control cannot drift between the two phases and
    quietly stop being comparable.
    """
    raw = (REPO_ROOT / agent_path(agent_id)).read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    frontmatter = parts[1] if len(parts) >= 3 else "\n"
    return f"---{frontmatter}---\n\n{FLATTENED_BODY}"


def prompt_for(task: dict, condition: str, run: str) -> str:
    if condition not in CONDITIONS:
        raise KeyError(condition)
    path = (CONTROLS / f"{task['agent']}.md").relative_to(REPO_ROOT).as_posix() \
        if condition == "flattened" else agent_path(task["agent"])
    return PROMPT_TEMPLATE.format(
        preamble=PREAMBLE[condition].format(agent_path=path),
        brief=task["brief"],
        out_path=artifact_path(run, condition, task
                               ).relative_to(REPO_ROOT).as_posix())


# --------------------------------------------------------------------------
# execution -- the only part that runs generated code, and it is local only


def load_suite(path: Path):
    spec = importlib.util.spec_from_file_location(f"suite_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_one(artifact: Path, suite: Path) -> dict:
    """One artifact, one suite, one subprocess. Never raises."""
    checks = {c["id"]: c["kind"] for c in load_suite(suite).CHECKS}

    def every(reason: str) -> dict:
        return {"import_error": reason,
                "checks": {cid: {"ok": False, "error": reason, "kind": kind}
                           for cid, kind in checks.items()}}

    if not artifact.exists():
        # Not writing the file is a failure of the task, not an error in the
        # harness, and it is recorded as such rather than skipped.
        return every("artifact was never written")

    with tempfile.TemporaryDirectory(prefix="construction-") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(RUNNER), str(artifact), str(suite)],
                capture_output=True, text=True, timeout=EXECUTE_TIMEOUT,
                cwd=scratch, check=False)
        except subprocess.TimeoutExpired:
            return every(f"timed out after {EXECUTE_TIMEOUT}s")

    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return every(f"runner produced no result: {tail[-1] if tail else '?'}")

    for cid, entry in raw["checks"].items():
        entry["kind"] = checks.get(cid, "?")
    return raw


def execute(run: str, suites: Path) -> dict:
    tasks = load_tasks()
    run_dir = ARTIFACTS / run
    if not run_dir.is_dir():
        raise SystemExit(f"no such run: {run_dir.relative_to(REPO_ROOT)}")

    conditions = sorted(p.name for p in run_dir.iterdir()
                        if p.is_dir() and p.name in CONDITIONS)
    out: dict = {}
    for condition in conditions:
        out[condition] = {}
        for task in tasks:
            artifact = artifact_path(run, condition, task)
            suite = suite_path(task, suites)
            result = run_one(artifact, suite)
            result["artifact_sha256"] = (sha256_file(artifact)
                                         if artifact.exists() else None)
            result["suite_sha256"] = sha256_file(suite)
            out[condition][task["task"]] = result
            done = sum(1 for c in result["checks"].values() if c["ok"])
            print(f"  {condition:<10} {task['task']}  "
                  f"{done}/{len(result['checks'])}"
                  + (f"  [{result['import_error']}]"
                     if result["import_error"] else ""))
    return {
        "_note": ("Written by eval_construction.py --execute, which is a LOCAL "
                  "command. CI never executes generated code -- it re-verifies "
                  "the digests below against the committed bytes and re-scores "
                  "these recorded outcomes."),
        "run": run,
        "python": sys.version.split()[0],
        "tasks_sha256": tasks_digest(tasks),
        "conditions": out,
    }


def run_set(suites: Path, directory: Path) -> dict[str, dict]:
    """Run every suite against one directory of implementations."""
    return {t["task"]: run_one(directory / t["module"], suite_path(t, suites))
            for t in load_tasks()}


def failures(result: dict, kind: str) -> dict[str, str]:
    return {cid: c["error"] for cid, c in result["checks"].items()
            if c["kind"] == kind and not c["ok"]}


def self_test(suites: Path, reference: Path) -> int:
    """Every suite against its reference. A check the reference fails is broken.

    The author of a fixture does not reliably know what is wrong with it -- the
    Phase 7 pilot found four real defects in code its own key called clean.
    This is the cheapest available correction: write the competent
    implementation first and let it referee the checks.
    """
    broken = 0
    for tid, result in run_set(suites, reference).items():
        bad = {cid: c["error"] for cid, c in result["checks"].items()
               if not c["ok"]}
        total = len(result["checks"])
        print(f"  {tid}  {total - len(bad)}/{total}  "
              f"{'ok' if not bad else f'{len(bad)} BROKEN'}")
        for cid, err in sorted(bad.items()):
            print(f"      {cid}: {err}")
        broken += len(bad)

    if broken:
        print(f"\nFAILED: {broken} check(s) reject the reference implementation.")
        print("The suite is wrong, not the reference. Fix the check.")
        return 1
    print("\nPASSED: every suite is satisfiable by a competent implementation.")
    return 0


def calibrate(suites: Path, naive: Path) -> int:
    """Every suite against a deliberately naive first draft.

    A suite that a careless implementation passes is not measuring anything,
    and this project has shipped five separate checks that were green while
    measuring nothing. Satisfiability (--self-test) is only half the proof;
    this is the other half, and the two assertions point in opposite
    directions:

        every STATED check must pass    -- the floor is reachable by someone
                                           who only read the brief, so a low
                                           stated rate in a real run means the
                                           answer is broken, not unspecialised
        at least one IMPLIED must fail  -- per task. A task where the naive
                                           draft passes everything cannot
                                           separate the conditions and is dead
                                           weight in the run
    """
    stated_broken, blind_tasks = 0, []
    for tid, result in run_set(suites, naive).items():
        bad_stated = failures(result, "stated")
        bad_implied = failures(result, "implied")
        flag = "ok" if bad_implied and not bad_stated else "CANNOT DISCRIMINATE"
        if bad_stated:
            flag = "STATED FLOOR UNREACHABLE"
        print(f"  {tid}  stated {len(bad_stated)} failed, "
              f"implied {len(bad_implied)} failed   {flag}")
        for cid, err in sorted(bad_implied.items()):
            print(f"      caught: {cid}: {err}")
        for cid, err in sorted(bad_stated.items()):
            print(f"      STATED: {cid}: {err}")
        stated_broken += len(bad_stated)
        if not bad_implied:
            blind_tasks.append(tid)

    if stated_broken:
        print(f"\nFAILED: {stated_broken} stated check(s) fail the naive draft. "
              f"The floor is not a floor.")
        return 1
    if blind_tasks:
        print(f"\nFAILED: {', '.join(blind_tasks)} pass every implied check "
              f"naively and cannot separate the conditions.")
        return 1
    print("\nPASSED: the floor is reachable and every task can discriminate.")
    return 0


# --------------------------------------------------------------------------
# scoring -- a pure function of committed JSON


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def score_condition(tasks_by_id: dict, results: dict) -> dict:
    per_task, kinds = [], {k: {"passed": 0, "total": 0} for k in KINDS}
    for tid in sorted(results):
        task, result = tasks_by_id[tid], results[tid]
        checks = result["checks"]
        row = {"task": tid, "agent": task["agent"], "module": task["module"],
               "imported": result["import_error"] is None,
               "import_error": result["import_error"], "by_kind": {}}
        for kind in KINDS:
            ids = [cid for cid, c in checks.items() if c["kind"] == kind]
            passed = [cid for cid in ids if checks[cid]["ok"]]
            row["by_kind"][kind] = {
                "passed": len(passed), "total": len(ids),
                "failed": sorted(set(ids) - set(passed)),
            }
            kinds[kind]["passed"] += len(passed)
            kinds[kind]["total"] += len(ids)
        per_task.append(row)

    for kind in KINDS:
        k = kinds[kind]
        k["pass_pct"] = pct(k["passed"], k["total"])

    passed = sum(k["passed"] for k in kinds.values())
    total = sum(k["total"] for k in kinds.values())
    return {
        "tasks": len(per_task),
        "modules_that_import": sum(1 for r in per_task if r["imported"]),
        # by_kind is the result. The combined figure below is here only so a
        # reader can see it is dominated by the stated floor, which is why it
        # is never the headline.
        "by_kind": kinds,
        "checks_passed": passed,
        "checks_total": total,
        "combined_pass_pct": pct(passed, total),
        "per_task": per_task,
    }


def load_results(tasks: list[dict], suites: Path) -> list[dict]:
    """Committed results, with every digest re-verified against current bytes."""
    by_id = {t["task"]: t for t in tasks}
    runs = []
    if not RESULTS.is_dir():
        return runs

    for path in sorted(RESULTS.glob("*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        data = json.loads(path.read_text(encoding="utf-8"))

        expected = tasks_digest(tasks)
        if data.get("tasks_sha256") != expected:
            raise SystemExit(
                f"{rel}: a brief or the prompt template changed after these "
                f"artifacts were written.\n  recorded "
                f"{data.get('tasks_sha256') or '(none)'}\n  current  {expected}\n"
                f"  Re-run the agents, or restore the brief. Editing a SUITE "
                f"does not trip this -- only the question does.")

        for condition, results in data["conditions"].items():
            for tid, result in results.items():
                artifact = artifact_path(data["run"], condition, by_id[tid])
                have = sha256_file(artifact) if artifact.exists() else None
                if have != result["artifact_sha256"]:
                    raise SystemExit(
                        f"{rel}: {condition}/{tid} was recorded against "
                        f"different bytes than are committed at "
                        f"{artifact.relative_to(REPO_ROOT).as_posix()}.\n"
                        f"  Re-run --execute {data['run']}.")
                suite = suite_path(by_id[tid], suites)
                if sha256_file(suite) != result["suite_sha256"]:
                    raise SystemExit(
                        f"{rel}: {condition}/{tid} was scored by an older "
                        f"{suite.relative_to(REPO_ROOT).as_posix()}.\n"
                        f"  Re-run --execute {data['run']} -- it is free.")
        data["_name"] = path.stem
        runs.append(data)
    return runs


def build_report(suites: Path) -> dict:
    tasks = load_tasks()
    by_id = {t["task"]: t for t in tasks}

    drifted = []
    for t in tasks:
        registered = t.get("suite_sha256_at_registration")
        current = sha256_file(suite_path(t, suites))
        if registered and registered != current:
            # Disclosed, not blocked. An amended key is legitimate; an
            # undisclosed one is not.
            drifted.append({"task": t["task"], "registered": registered,
                            "current": current})

    runs = []
    for data in load_results(tasks, suites):
        conditions = {c: score_condition(by_id, r)
                      for c, r in sorted(data["conditions"].items())}
        base = conditions.get("none")
        lift = {}
        if base:
            for kind in KINDS:
                lift[kind] = {
                    c: round(v["by_kind"][kind]["pass_pct"]
                             - base["by_kind"][kind]["pass_pct"], 2)
                    for c, v in conditions.items()}
        runs.append({
            "run": data["run"], "python": data.get("python"),
            "conditions": conditions,
            "lift_over_no_skill": lift,
            "_note": ("lift_over_no_skill['implied'] is the figure this phase "
                      "exists for. Read it ONLY if the stated rate is near "
                      "ceiling in every condition -- if it is not, the answers "
                      "failed for reasons unrelated to the agent file."),
        })

    return {
        "_note": ("Generated by scripts/eval_construction.py from the committed "
                  "artifacts and the committed results in "
                  "eval/construction/results/. Scoring is a pure function of "
                  "committed data -- no model is called and no generated code "
                  "is executed here, which is what lets CI verify it."),
        "tasks": {"total": len(tasks), "tasks_sha256": tasks_digest(tasks)},
        "conditions": CONDITIONS,
        "suites_amended_since_registration": drifted,
        "runs": runs,
    }


def report_table(report: dict) -> None:
    for r in report["runs"]:
        print(f"{r['run']}  [python {r['python']}]")
        print(f"  {'condition':<11}{'stated':>16}{'implied':>16}"
              f"{'imports':>10}{'implied vs none':>18}")
        for cond in ("none", "current", "candidate", "flattened"):
            c = r["conditions"].get(cond)
            if not c:
                continue
            cells = []
            for kind in KINDS:
                k = c["by_kind"][kind]
                cells.append(f"{k['passed']}/{k['total']} ({k['pass_pct']}%)".rjust(16))
            delta = r["lift_over_no_skill"].get("implied", {}).get(cond)
            print(f"  {cond:<11}" + "".join(cells)
                  + f"{c['modules_that_import']}/{c['tasks']}".rjust(10)
                  + (f"{delta:>+18}" if delta is not None and cond != "none"
                     else " " * 18))
        print()

    if report["suites_amended_since_registration"]:
        print("Suites amended since registration (disclosed, not an error):")
        for d in report["suites_amended_since_registration"]:
            print(f"  {d['task']}")
        print()


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prompt", metavar="TASK")
    ap.add_argument("--condition", default="current", choices=sorted(CONDITIONS))
    ap.add_argument("--run", metavar="NAME")
    ap.add_argument("--conditions", action="store_true")
    ap.add_argument("--checks", action="store_true",
                    help="print the acceptance catalogue: every check and why")
    ap.add_argument("--digest", nargs="*", metavar="TASK")
    ap.add_argument("--execute", metavar="RUN",
                    help="LOCAL ONLY: import each artifact and run its suite")
    ap.add_argument("--self-test", action="store_true",
                    help="run every suite against its reference implementation")
    ap.add_argument("--calibrate", action="store_true",
                    help="run every suite against a deliberately naive draft: "
                         "proves the checks can fail, not just pass")
    ap.add_argument("--emit-controls", action="store_true")
    ap.add_argument("--suites", default=str(SUITES), metavar="DIR",
                    help="where the acceptance suites live (they are kept "
                         "outside the tree while answers are collected)")
    ap.add_argument("--reference", default=str(REFERENCE), metavar="DIR")
    ap.add_argument("--naive", default=str(NAIVE), metavar="DIR")
    args = ap.parse_args()
    suites, reference = Path(args.suites), Path(args.reference)

    if args.emit_controls:
        CONTROLS.mkdir(parents=True, exist_ok=True)
        for agent in sorted({t["agent"] for t in load_tasks()}):
            out = CONTROLS / f"{agent}.md"
            out.write_text(flattened_text(agent), encoding="utf-8", newline="\n")
            print(f"wrote {out.relative_to(REPO_ROOT).as_posix()}")
        return 0

    if args.conditions:
        for name, why in CONDITIONS.items():
            print(f"{name:<11} {why}\n")
        return 0

    if args.checks:
        for task in load_tasks():
            print(f"{task['task']}  {task['agent']}")
            for check in load_suite(suite_path(task, suites)).CHECKS:
                print(f"  [{check['kind']:<7}] {check['id']}\n"
                      f"      what: {check['what']}\n      why:  {check['why']}")
            print()
        return 0

    if args.digest is not None:
        print(tasks_digest(load_tasks(), args.digest or None))
        return 0

    if args.self_test:
        return self_test(suites, reference)

    if args.calibrate:
        return calibrate(suites, Path(args.naive))

    if args.prompt:
        task = next((t for t in load_tasks() if t["task"] == args.prompt), None)
        if task is None:
            print(f"No such task: {args.prompt}", file=sys.stderr)
            return 1
        if not args.run:
            print("--prompt needs --run NAME: the artifact path is part of "
                  "the prompt.", file=sys.stderr)
            return 1
        sys.stdout.write(prompt_for(task, args.condition, args.run))
        return 0

    if args.execute:
        RESULTS.mkdir(parents=True, exist_ok=True)
        print(f"Executing {args.execute} -- this imports model-generated code.")
        data = execute(args.execute, suites)
        out = RESULTS / f"{args.execute}.json"
        out.write_bytes(dump_json(data))
        print(f"\nWrote {out.relative_to(REPO_ROOT).as_posix()}")
        return 0

    report = build_report(suites)
    blob = dump_json(report)

    if args.check:
        if not report["runs"]:
            print("PASSED: no executed runs yet; nothing to verify.")
            return 0
        if not BASELINE.exists():
            print(f"FAILED: {BASELINE.relative_to(REPO_ROOT).as_posix()} is "
                  f"missing. Run the script with no arguments.", file=sys.stderr)
            return 1
        if BASELINE.read_bytes() != blob:
            print("FAILED: the committed baseline does not match the committed "
                  "artifacts and results.", file=sys.stderr)
            return 1
        print(f"PASSED: {report['tasks']['total']} tasks, "
              f"{len(report['runs'])} run(s), baseline matches.")
        return 0

    if not report["runs"]:
        print(f"Tasks: {report['tasks']['total']}  "
              f"digest {report['tasks']['tasks_sha256'][:12]}")
        print("No executed runs yet. Generate prompts with --prompt <task> "
              "--condition <c> --run <name>,\ncollect artifacts blind, then "
              "--execute <name>.")
        return 0

    BASELINE.write_bytes(blob)
    print(f"Tasks: {report['tasks']['total']}\n")
    report_table(report)
    print(f"Wrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
