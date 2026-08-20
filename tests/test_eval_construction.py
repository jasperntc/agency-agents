#!/usr/bin/env python3
"""Tests for scripts/eval_construction.py.

This phase executes model-written code and grades it against a key the author
also wrote. Both halves have failed before in this repository, so these assert
the properties whose absence made each failure possible.

  THE SUITE IS SATISFIABLE   The Phase 7 pilot found four real defects in code
                             its own answer key called clean. The author of a
                             fixture does not know what is wrong with it. Every
                             suite must therefore pass a competent reference
                             implementation, or the check is broken, not the
                             answer.
  THE SUITE CAN FAIL         Five separate checks in this project have been
                             green while measuring nothing. Satisfiability is
                             only half the proof: a deliberately naive draft
                             must pass every STATED check and fail at least one
                             IMPLIED check per task, or that task cannot
                             separate the conditions.
  THE DIGEST IGNORES THE KEY The digest binds to the QUESTION. Correcting a
                             suite must not invalidate artifacts that are still
                             answers to the same brief -- the Phase 7 oracle was
                             rebuilt twice and both rebuilds were right.
  THE BRIEF DOES NOT LEAK    An implied requirement named in the brief is a
                             stated requirement, and all three conditions would
                             meet it. That is how a construction test quietly
                             stops measuring anything.
  IDENTICAL DELIVERY         Conditions differ only in the agent file. Handing
                             one a path and another inline text would measure
                             the delivery mechanism.
  NO AGGREGATE HIDES A KIND  stated and implied are never blended into the
                             figure the phase is read from.
  EVERY ARM NAMES ITS MODEL  A run is one model's answers. Two runs are two
                             arms, and an arm whose model is unrecorded cannot
                             be read. The run NAME is a label, not a record --
                             the first run here was `2026-08-18-subagent-c6`
                             and said nothing about Opus.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_construction as ec  # noqa: E402
from lib.corpus import dump_json  # noqa: E402

# Vocabulary that would give away an implied requirement if it appeared in a
# brief. Kept here rather than in the suites so the pre-registered suite hashes
# stay untouched. Substring match, case-insensitive.
LEAKS = {
    "c001": ("symmetr", "rounding", "round half", "validate", "boundary",
             "invalid", "outside"),
    "c002": ("keyset", "offset", "tie", "stable", "insert", "duplicate",
             "skip", "opaque"),
    "c003": ("idempot", "replay", "retry", "duplicate", "out-of-order",
             "mutate", "in place", "newer than"),
    "c004": ("hash", "hmac", "reversib", "mask", "mutate", "in place",
             "linkage", "re-identif"),
    "c005": ("teen", "modulo", "modulus", "exception", "11", "12", "21"),
    "c006": ("hmac", "constant-time", "cover", "splice", "tamper", "forge",
             "prefix", "payload"),
    # c007's whole discriminator is that the anchor day is preserved and
    # clamped per month rather than carried forward. Naming any shape that
    # idea takes -- the anchor itself, the drift it prevents, the short
    # months that expose it, or the leap year that proves it -- would turn
    # the implied requirement into a stated one.
    "c007": ("anchor", "drift", "clamp", "leap", "last day", "end of month",
             "month-end", "shorter", "28", "29", "30th", "31"),
}

MIN_PER_KIND = 4


def suites_present() -> bool:
    return ec.SUITES.is_dir() and any(ec.SUITES.glob("c*.py"))


class Tasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = ec.load_tasks()

    def test_task_ids_are_unique(self):
        ids = [t["task"] for t in self.tasks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_agent_file_exists(self):
        for t in self.tasks:
            self.assertTrue((REPO_ROOT / ec.agent_path(t["agent"])).exists(),
                            f"{t['task']}: {t['agent']}")

    def test_module_names_are_unique_and_are_python(self):
        modules = [t["module"] for t in self.tasks]
        self.assertEqual(len(modules), len(set(modules)))
        for module in modules:
            self.assertTrue(module.endswith(".py"), module)

    def test_every_task_declares_the_suite_it_registered(self):
        for t in self.tasks:
            self.assertRegex(t["suite_sha256_at_registration"], r"^[0-9a-f]{64}$")

    def test_every_task_says_why_it_is_here(self):
        """...in its SUITE, which is withheld, not in the question file."""
        if not suites_present():
            self.skipTest("suites not in the tree")
        for t in self.tasks:
            suite = ec.load_suite(ec.suite_path(t, ec.SUITES))
            self.assertTrue(getattr(suite, "WHY_THIS_TASK", "").strip(),
                            f"{t['task']} does not say why it is in the set")

    def test_the_question_file_does_not_explain_the_discriminator(self):
        """`why` names the answer, so it cannot live in a file answerers read.

        It did, for every task, from the day the phase was built: c002's read
        "Offset paging ... breaks the moment a row is inserted", which is the
        implied check in one sentence. The blindness guard only ever inspected
        `brief`, so nothing caught it, and every construction result collected
        before this fix was gathered with the discriminators sitting in
        eval/construction/tasks.jsonl inside the repository the answerers could
        read.
        """
        for t in self.tasks:
            self.assertNotIn(
                "why", t,
                f"{t['task']} carries `why` in tasks.jsonl again -- it names "
                f"the discriminator and belongs in the withheld suite")


class Blindness(unittest.TestCase):
    """The answer key is the suite, so the question must not contain it."""

    @classmethod
    def setUpClass(cls):
        cls.tasks = ec.load_tasks()

    def test_no_brief_names_an_implied_requirement(self):
        for t in self.tasks:
            brief = t["brief"].lower()
            for leak in LEAKS[t["task"]]:
                self.assertNotIn(leak, brief,
                                 f"{t['task']}: the brief says {leak!r}, which "
                                 f"turns an implied requirement into a stated "
                                 f"one and every condition would meet it")

    def test_every_task_has_a_leak_vocabulary(self):
        # A task added without one would be exempt from the check above by
        # accident rather than by decision.
        for t in self.tasks:
            self.assertIn(t["task"], LEAKS, f"{t['task']} has no leak list")

    def test_the_prompt_never_mentions_how_it_is_graded(self):
        # "test" is deliberately NOT on this list: the prompt has to say "no
        # tests" to stop an answerer writing its own, and forbidding the word
        # would forbid the instruction.
        low = ec.PROMPT_TEMPLATE.lower()
        for word in ("implied", "stated", "acceptance", "grade", "score",
                     "requirement", "edge case"):
            self.assertNotIn(word, low, f"the prompt template says {word!r}")

    def test_conditions_differ_only_in_the_agent_file(self):
        task = self.tasks[0]
        bodies = set()
        for condition in ("none", "current", "flattened"):
            body = ec.prompt_for(task, condition, "probe").split("BRIEF", 1)[1]
            # The output path carries the condition by design -- each writes to
            # its own directory so the artifacts cannot collide. Normalise it
            # out; everything else after the preamble must be identical.
            bodies.add(body.replace(f"/{condition}/", "/<condition>/"))
        self.assertEqual(len(bodies), 1,
                         "the conditions differ somewhere other than the "
                         "preamble and their output directory")

    def test_the_control_is_a_file_at_a_path_like_the_real_one(self):
        task = self.tasks[0]
        flat = ec.prompt_for(task, "flattened", "probe")
        self.assertIn(f"eval/construction/flattened/{task['agent']}.md", flat)
        self.assertNotIn(ec.FLATTENED_BODY.splitlines()[0], flat,
                         "the control was inlined instead of linked")

    def test_the_control_differs_from_the_real_agent_file(self):
        for t in self.tasks:
            control = ec.CONTROLS / f"{t['agent']}.md"
            self.assertTrue(control.exists(), f"{t['agent']}: run --emit-controls")
            real = (REPO_ROOT / ec.agent_path(t["agent"])).read_text(encoding="utf-8")
            self.assertNotEqual(control.read_text(encoding="utf-8"), real,
                                f"{t['agent']}: the positive control is the "
                                f"real file")

    def test_no_artifact_quotes_a_check_from_its_suite(self):
        """An artifact naming a check id read the key rather than the brief."""
        if not suites_present():
            self.skipTest("suites not in the tree")
        for t in ec.load_tasks():
            ids = [c["id"] for c in
                   ec.load_suite(ec.suite_path(t, ec.SUITES)).CHECKS]
            for artifact in ec.ARTIFACTS.rglob(t["module"]):
                text = artifact.read_text(encoding="utf-8", errors="replace")
                for cid in ids:
                    self.assertNotIn(cid, text,
                                     f"{artifact.name} names {cid}")


class Instrument(unittest.TestCase):
    """Can the suites pass, and -- the half that gets skipped -- can they fail?"""

    @classmethod
    def setUpClass(cls):
        if not suites_present():
            raise unittest.SkipTest("suites not in the tree")
        cls.tasks = ec.load_tasks()

    def test_every_check_declares_a_kind_a_what_and_a_why(self):
        for t in self.tasks:
            for check in ec.load_suite(ec.suite_path(t, ec.SUITES)).CHECKS:
                self.assertIn(check["kind"], ec.KINDS, check["id"])
                self.assertTrue(check["what"].strip(), check["id"])
                self.assertTrue(check["why"].strip(), check["id"])

    def test_check_ids_are_prefixed_by_their_kind(self):
        prefix = {"stated": "s_", "implied": "i_"}
        for t in self.tasks:
            for check in ec.load_suite(ec.suite_path(t, ec.SUITES)).CHECKS:
                self.assertTrue(check["id"].startswith(prefix[check["kind"]]),
                                f"{check['id']} is {check['kind']}")

    def test_every_check_has_a_function(self):
        for t in self.tasks:
            suite = ec.load_suite(ec.suite_path(t, ec.SUITES))
            for check in suite.CHECKS:
                self.assertTrue(callable(getattr(suite, f"check_{check['id']}",
                                                 None)),
                                f"{t['task']}: no function for {check['id']}")

    def test_every_task_carries_enough_of_both_kinds(self):
        for t in self.tasks:
            checks = ec.load_suite(ec.suite_path(t, ec.SUITES)).CHECKS
            for kind in ec.KINDS:
                n = sum(1 for c in checks if c["kind"] == kind)
                self.assertGreaterEqual(
                    n, MIN_PER_KIND,
                    f"{t['task']}: only {n} {kind} checks")

    def test_the_reference_passes_every_check(self):
        """Satisfiability. A check the reference fails is a broken check."""
        for tid, result in ec.run_set(ec.SUITES, ec.REFERENCE).items():
            bad = {cid: c["error"] for cid, c in result["checks"].items()
                   if not c["ok"]}
            self.assertFalse(bad, f"{tid}: reference rejected by {bad}")

    def test_the_naive_draft_reaches_the_stated_floor(self):
        """If someone who only read the brief cannot pass `stated`, a low
        stated rate in a real run means the brief is hard, not the answer bad."""
        for tid, result in ec.run_set(ec.SUITES, ec.NAIVE).items():
            bad = ec.failures(result, "stated")
            self.assertFalse(bad, f"{tid}: the floor is not a floor -- {bad}")

    def test_every_task_can_separate_the_conditions(self):
        """THE anti-vacuity test. A task the naive draft passes outright
        contributes nothing but noise to the comparison."""
        for tid, result in ec.run_set(ec.SUITES, ec.NAIVE).items():
            self.assertTrue(
                ec.failures(result, "implied"),
                f"{tid}: a naive draft passes every implied check, so this "
                f"task cannot show a difference between the conditions")


class Digest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = ec.load_tasks()

    def test_digest_is_stable(self):
        self.assertEqual(ec.tasks_digest(self.tasks),
                         ec.tasks_digest(self.tasks))

    def test_digest_covers_the_prompt_template(self):
        before = ec.tasks_digest(self.tasks)
        original = ec.PROMPT_TEMPLATE
        try:
            ec.PROMPT_TEMPLATE = original + "\nAlso mention edge cases.\n"
            self.assertNotEqual(before, ec.tasks_digest(self.tasks))
        finally:
            ec.PROMPT_TEMPLATE = original

    def test_digest_covers_the_brief(self):
        before = ec.tasks_digest(self.tasks)
        edited = [dict(t) for t in self.tasks]
        edited[0]["brief"] += " Handle invalid input."
        self.assertNotEqual(before, ec.tasks_digest(edited))

    def test_digest_ignores_the_acceptance_suite(self):
        """Correcting the key must not invalidate answers to the same question.

        This property is what let twelve Phase 7 answers be re-scored for free
        after the oracle was rebuilt, and it paid off four times.
        """
        if not suites_present():
            self.skipTest("suites not in the tree")
        before = ec.tasks_digest(self.tasks)
        suite = ec.suite_path(self.tasks[0], ec.SUITES)
        original = suite.read_bytes()
        try:
            suite.write_bytes(original + b"\n# a corrected comment\n")
            self.assertEqual(before, ec.tasks_digest(ec.load_tasks()))
        finally:
            suite.write_bytes(original)

    def test_registering_a_new_task_does_not_invalidate_old_answers(self):
        """A run is bound to the questions IT was asked, not to the registry.

        The digest was originally taken over every task in tasks.jsonl and
        compared the same way, so adding c007 invalidated both committed c6
        arms and demanded they be re-run to gain one task. That makes the task
        set unable to grow, which is the opposite of what a benchmark needs --
        and the pressure it creates is to leave the benchmark too easy, which
        is exactly the state c007 exists to fix.

        Scoping is not a loosening: editing a brief a run DID answer still
        invalidates it, which is the next test.
        """
        answered = [t["task"] for t in self.tasks][:-1]
        before = ec.tasks_digest(self.tasks, answered)
        added = self.tasks + [dict(self.tasks[0], task="zzz_new",
                                   brief="A brand new question.")]
        self.assertEqual(
            before, ec.tasks_digest(added, answered),
            "registering an extra task changed the digest of a run that "
            "never saw it -- committed arms would have to be re-run to add "
            "a task")

    def test_scoping_still_catches_an_edited_brief(self):
        """The half of the guard that must survive the scoping fix."""
        answered = [t["task"] for t in self.tasks]
        before = ec.tasks_digest(self.tasks, answered)
        edited = [dict(t) for t in self.tasks]
        edited[0]["brief"] += " Handle invalid input."
        self.assertNotEqual(
            before, ec.tasks_digest(edited, answered),
            "editing an answered brief no longer invalidates the run")

    def test_digest_ignores_the_registration_hash(self):
        before = ec.tasks_digest(self.tasks)
        edited = [dict(t) for t in self.tasks]
        edited[0]["suite_sha256_at_registration"] = "0" * 64
        self.assertEqual(before, ec.tasks_digest(edited))


class Results(unittest.TestCase):
    """The lockfile is what makes --check pure. It has to actually lock."""

    @classmethod
    def setUpClass(cls):
        cls.tasks = ec.load_tasks()
        if not suites_present() or not any(ec.RESULTS.glob("*.json")):
            raise unittest.SkipTest("no executed run in the tree")

    def _probe(self, mutate) -> None:
        source = sorted(ec.RESULTS.glob("*.json"))[0]
        data = json.loads(source.read_text(encoding="utf-8"))
        mutate(data)
        probe = ec.RESULTS / "_zz-probe.json"
        probe.write_bytes(dump_json(data))
        try:
            with self.assertRaises(SystemExit) as ctx:
                ec.load_results(self.tasks, ec.SUITES)
            return str(ctx.exception)
        finally:
            probe.unlink()

    def test_results_recorded_against_other_bytes_are_a_hard_error(self):
        def mutate(data):
            condition = sorted(data["conditions"])[0]
            tid = sorted(data["conditions"][condition])[0]
            data["conditions"][condition][tid]["artifact_sha256"] = "0" * 64
        self.assertIn("different bytes", self._probe(mutate))

    def test_results_scored_by_an_older_suite_are_a_hard_error(self):
        def mutate(data):
            condition = sorted(data["conditions"])[0]
            tid = sorted(data["conditions"][condition])[0]
            data["conditions"][condition][tid]["suite_sha256"] = "0" * 64
        self.assertIn("older", self._probe(mutate))

    def test_a_changed_brief_invalidates_the_run(self):
        def mutate(data):
            data["tasks_sha256"] = "0" * 64
        self.assertIn("changed after these artifacts", self._probe(mutate))

    def test_the_clean_tree_loads(self):
        ec.load_results(self.tasks, ec.SUITES)

    def test_registering_a_task_does_not_invalidate_committed_runs(self):
        """The call site, not just the digest function.

        tasks_digest() has always taken a task_ids filter; nothing passed one,
        so verification re-derived every run's digest over the WHOLE registry.
        Registering c007 therefore invalidated both committed c6 arms, and the
        only ways out were to re-run 36 subagents or to leave the benchmark at
        the ceiling that made it useless. This asserts the fix where it
        actually has to hold.
        """
        extra = dict(self.tasks[0], task="zzz_probe",
                     brief="A question no committed run has ever been asked.",
                     module="zzz_probe.py")
        try:
            ec.load_results(self.tasks + [extra], ec.SUITES)
        except SystemExit as exc:
            # Caught rather than propagated: load_results exits the process,
            # which would abort the whole test run instead of reporting one
            # failure.
            self.fail(f"registering an unanswered task invalidated a "
                      f"committed run: {exc}")

    def test_a_run_is_never_scored_on_a_question_it_was_not_asked(self):
        """Registering c007 must not restate the c6 arms as 24/28.

        --execute iterated every task in tasks.jsonl, so re-scoring a 6-task
        arm after a 7th was registered recorded the new task as
        "artifact was never written" and dropped both published arms from
        100% to 85.71%. The arms did not get worse; they were asked a
        question that did not exist when they ran.
        """
        for run in sorted(ec.RESULTS.glob("*.json")):
            data = json.loads(run.read_text(encoding="utf-8"))
            answered = {tid for results in data["conditions"].values()
                        for tid in results}
            for condition, results in data["conditions"].items():
                for tid, result in results.items():
                    self.assertIn(tid, answered)
                    self.assertNotEqual(
                        result.get("import_error"), "artifact was never written",
                        f"{run.name}: {condition}/{tid} is recorded as an "
                        f"unwritten artifact -- a task registered after the "
                        f"run has been scored against it")

    def test_an_edited_brief_still_invalidates_a_run_that_answered_it(self):
        """The other side of the same fix -- scoping must not be a loosening."""
        edited = [dict(t) for t in self.tasks]
        edited[0]["brief"] += " Also handle invalid input."
        with self.assertRaises(SystemExit) as ctx:
            ec.load_results(edited, ec.SUITES)
        self.assertIn("changed after these artifacts", str(ctx.exception))


class Report(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not suites_present():
            raise unittest.SkipTest("suites not in the tree")
        cls.report = ec.build_report(ec.SUITES)

    def test_report_is_byte_stable(self):
        self.assertEqual(dump_json(self.report),
                         dump_json(ec.build_report(ec.SUITES)))

    def test_both_controls_are_described(self):
        self.assertIn("CONTROL", ec.CONDITIONS["none"])
        self.assertIn("POSITIVE CONTROL", ec.CONDITIONS["flattened"])

    def test_lift_is_reported_per_kind_and_never_blended(self):
        for run in self.report["runs"]:
            if not run["lift_over_no_skill"]:
                continue
            self.assertEqual(set(run["lift_over_no_skill"]), set(ec.KINDS),
                             "lift must be per kind: a combined figure is "
                             "dominated by the stated floor and would hide the "
                             "only number this phase exists for")

    def test_every_condition_keeps_its_kinds_apart(self):
        for run in self.report["runs"]:
            for condition in run["conditions"].values():
                self.assertEqual(set(condition["by_kind"]), set(ec.KINDS))

    def test_amended_suites_are_disclosed(self):
        self.assertIn("suites_amended_since_registration", self.report)

    def test_every_run_records_the_model_that_produced_it(self):
        for run in self.report["runs"]:
            self.assertTrue(
                run.get("model"),
                f"{run['run']} records no model. A lift figure is unreadable "
                f"without knowing what produced it, and the run name is a "
                f"label rather than a record.")

    def test_check_rejects_a_run_that_names_no_model(self):
        """The guard has to be able to fail, or it is not a guard.

        Proven end to end through the CLI rather than by calling a predicate.
        The assertion lives inside main(); a test of a helper main() did not
        call would be exactly the kind of green check that measures nothing,
        which this project has now found five times.
        """
        sources = sorted(ec.RESULTS.glob("*.json"))
        if not sources:
            self.skipTest("no executed run")
        data = json.loads(sources[0].read_text(encoding="utf-8"))
        data.pop("model", None)
        probe = ec.RESULTS / "_zz-nomodel.json"
        probe.write_bytes(dump_json(data))
        try:
            proc = subprocess.run(
                [sys.executable,
                 str(ec.REPO_ROOT / "scripts" / "eval_construction.py"),
                 "--check"],
                capture_output=True, text=True, cwd=str(ec.REPO_ROOT))
            self.assertEqual(proc.returncode, 1,
                             f"--check passed a run with no model. "
                             f"{proc.stdout}{proc.stderr}")
            self.assertIn("record no model", proc.stderr)
        finally:
            probe.unlink()

    def test_the_committed_baseline_matches(self):
        if not self.report["runs"]:
            self.skipTest("no executed run")
        self.assertTrue(ec.BASELINE.exists(),
                        "run scripts/eval_construction.py to write it")
        self.assertEqual(ec.BASELINE.read_bytes(), dump_json(self.report),
                         "the baseline is stale; re-run the script")


if __name__ == "__main__":
    unittest.main(verbosity=2)
