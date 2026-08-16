#!/usr/bin/env python3
"""Tests for scripts/eval_selection.py.

Two things here are load-bearing and everything else is bookkeeping:

  1. BLINDNESS. If the generated prompt ever leaks `expect`, every recorded
     number becomes worthless and nothing else in the file would notice.
  2. THE DIGEST BINDING. It decides which recorded runs survive a benchmark
     edit. Too strict and correcting a known-wrong expectation costs a full
     re-run, which is a standing incentive to leave the benchmark wrong; too
     loose and picks get silently re-scored against questions nobody asked.

The digest tests run against literal dicts rather than the real cases file, so
they assert the RULE rather than today's data.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_selection as es  # noqa: E402
from lib.corpus import dump_json  # noqa: E402

BASELINE = REPO_ROOT / "metrics" / "selection-baseline.json"

CASES = [
    {"case": "c002", "kind": "independent", "task": "second task",
     "expect": ["b"], "why": "because"},
    {"case": "c001", "kind": "independent", "task": "first task",
     "expect": ["a"], "why": "because"},
]


def edited(case_id: str, **changes) -> list[dict]:
    return [dict(c, **changes) if c["case"] == case_id else dict(c)
            for c in CASES]


class TasksDigest(unittest.TestCase):
    """What may change under a run's feet, and what may not."""

    def test_expect_is_not_hashed(self):
        """The correction this guard was redesigned to permit.

        A blind subagent never sees `expect`. Binding picks to it means one
        corrected expectation destroys every answer in the file, which makes
        the honest move the expensive one.
        """
        self.assertEqual(
            es.tasks_digest(CASES),
            es.tasks_digest(edited("c001", expect=["totally", "different"])),
        )

    def test_why_and_kind_are_not_hashed(self):
        self.assertEqual(
            es.tasks_digest(CASES),
            es.tasks_digest(edited("c001", why="rewritten", kind="adversarial")),
        )

    def test_editing_a_task_changes_the_digest(self):
        """The failure the guard exists to catch: a different question."""
        self.assertNotEqual(
            es.tasks_digest(CASES),
            es.tasks_digest(edited("c001", task="first task, reworded")),
        )

    def test_adding_a_case_leaves_earlier_runs_valid(self):
        """A run is bound to what it answered, not to the benchmark's size.

        `cases.total` is ratcheted, so cases only ever grow. A digest over the
        whole set would invalidate every historical run on every future
        addition. Incompleteness is reported by `cases_missing` instead.
        """
        grown = CASES + [{"case": "c003", "kind": "independent",
                          "task": "third task", "expect": ["c"], "why": "w"}]
        answered = [c["case"] for c in CASES]
        self.assertEqual(es.tasks_digest(CASES, answered),
                         es.tasks_digest(grown, answered))

    def test_digest_is_independent_of_case_order(self):
        self.assertEqual(es.tasks_digest(CASES),
                         es.tasks_digest(list(reversed(CASES))))

    def test_subset_differs_from_full_set(self):
        """A pilot's digest is not a full run's, and must not be interchangeable."""
        self.assertNotEqual(es.tasks_digest(CASES),
                            es.tasks_digest(CASES, ["c001"]))


class RecordedRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = es.load_cases()

    def test_every_recorded_run_still_answers_the_current_questions(self):
        """`load_runs` raises SystemExit when it does not. Nothing else needed."""
        runs = es.load_runs(self.cases)
        self.assertTrue(runs, "no recorded runs found")

    def test_a_reworded_task_is_rejected(self):
        """The guard actually fires -- asserted, not assumed.

        A test that only checks the happy path would pass just as well if the
        comparison were `!=`, or if it had been deleted.
        """
        mutated = [dict(c, task=c["task"] + " (reworded)") if c["case"] == "c001"
                   else c for c in self.cases]
        with self.assertRaises(SystemExit):
            es.load_runs(mutated)

    def test_picks_name_agents_that_exist(self):
        """Not a gate -- a hallucinated pick is a real result and stays recorded.

        This asserts the CURRENT files are clean, so the `picked_nonexistent_agent`
        field is known to be reporting zero rather than silently broken.
        """
        known = es.agent_ids()
        for path in sorted(es.RESPONSES.glob("*.json")):
            run = json.loads(path.read_text(encoding="utf-8"))
            for cid, pick in run["picks"].items():
                if pick["agent"] == "NONE":
                    continue
                self.assertIn(pick["agent"], known,
                              f"{path.name} {cid}: no such agent id")


class Blindness(unittest.TestCase):
    """The prompt carries the question and nothing that answers it."""

    @classmethod
    def setUpClass(cls):
        cls.cases = es.load_cases()

    def test_prompt_leaks_no_expected_agent(self):
        for case in self.cases:
            prompt = es.prompt_for(case)
            for agent in case["expect"]:
                self.assertNotIn(agent, prompt,
                                 f"{case['case']}: prompt names the answer")

    def test_prompt_leaks_no_rationale_or_kind(self):
        for case in self.cases:
            prompt = es.prompt_for(case)
            self.assertNotIn(case["why"], prompt, case["case"])
            self.assertNotIn(f'"{case["kind"]}"', prompt, case["case"])

    def test_prompt_is_only_the_template_and_the_task(self):
        """Blocks the slow leak: routing hints accumulating in the prompt.

        Advice added here would measure this file rather than SKILL.md, which
        is the artifact consumers actually receive.
        """
        case = self.cases[0]
        self.assertEqual(
            es.prompt_for(case),
            es.PROMPT_TEMPLATE.format(
                skill=es.SKILL.relative_to(REPO_ROOT).as_posix(),
                task=case["task"]))


class Scoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = es.build_report()

    def test_committed_baseline_is_current(self):
        self.assertEqual(
            BASELINE.read_bytes(), dump_json(self.report),
            "metrics/selection-baseline.json is stale. "
            "Run ./scripts/eval_selection.py")

    def test_every_scored_case_lands_in_exactly_one_cell(self):
        """The cross-tab partitions. A case in two cells double-counts."""
        for run in self.report["runs"]:
            cells = run["outcome_cells"]
            placed = [cid for ids in cells.values() for cid in ids]
            self.assertEqual(len(placed), len(set(placed)),
                             f"{run['run']}: a case appears in two cells")
            self.assertEqual(
                sorted(placed + run["declined"]),
                sorted(r["case"] for r in run["per_case"]),
                f"{run['run']}: cells plus declines do not cover the run")

    def test_accuracy_matches_the_cells(self):
        """The headline number is not computed independently of the breakdown."""
        for run in self.report["runs"]:
            c = run["outcome_cells"]
            correct = len(c["reachable_correct"]) + len(c["translated"])
            self.assertEqual(
                round(100.0 * correct / run["cases_scored"], 2),
                run["accuracy_pct"], run["run"])

    def test_report_is_byte_stable(self):
        self.assertEqual(dump_json(es.build_report()),
                         dump_json(es.build_report()))


class Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = es.load_cases()

    def test_sample_is_deterministic(self):
        self.assertEqual(es.sample(self.cases, 15), es.sample(self.cases, 15))

    def test_sample_is_not_the_first_n_cases(self):
        """The bias `sample()` exists to avoid -- authoring order."""
        picked = [c["case"] for c in es.sample(self.cases, 15)]
        first_n = [c["case"] for c in sorted(
            self.cases, key=lambda c: c["case"])[:15]]
        self.assertNotEqual(picked, first_n)

    def test_recorded_pilot_matches_the_sampler(self):
        """The pilot file's cases are the ones `--sample 15` still selects.

        Guards a silent drift: if `sample()` changed, the recorded pilot would
        no longer be the subset it claims to be, and its numbers would be
        quoted as stratified when they were not.
        """
        pilot = json.loads(
            (es.RESPONSES / "2026-08-15-subagent-pilot15.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(sorted(pilot["picks"]),
                         [c["case"] for c in es.sample(self.cases, 15)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
