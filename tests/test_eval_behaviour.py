#!/usr/bin/env python3
"""Tests for scripts/eval_behaviour.py.

The prose-matching oracle this replaced was invalidated by its own first pilot:
the generic positive control beat the real agent by 25 points on wording luck
alone. These assert the properties whose absence made that possible, plus the
ones that make a line-citation oracle sound.

  RANGES MUST NOT OVERLAP  One citation scoring two defects would inflate recall
                           silently.
  RANGES MUST BE REAL      A range past the end of the fixture is unhittable, so
                           the defect is permanently missed and looks like a
                           finding about the agent.
  THE CONTROL IS A CONTROL `flattened` must deliver a different file from
                           `current`. It did not in the first draft.
  IDENTICAL DELIVERY       Conditions differ only in the agent file.
  DIGEST COVERS THE PROMPT The pilot was answered under a template that never
                           asked for lines. A digest blind to the template would
                           have let those answers be re-scored by an oracle they
                           could not satisfy, and nine of twelve would have
                           scored zero as an artifact.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_behaviour as eb  # noqa: E402


class Tasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = eb.load_tasks()

    def test_task_ids_are_unique(self):
        ids = [t["task"] for t in self.tasks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_agent_and_fixture_exists(self):
        for t in self.tasks:
            self.assertTrue((REPO_ROOT / eb.agent_path(t["agent"])).exists(), t["task"])
            self.assertTrue((eb.FIXTURES / t["fixture"]).exists(), t["task"])

    def test_every_task_has_planted_defects(self):
        for t in self.tasks:
            self.assertTrue(t["planted"], f"{t['task']}: nothing to find")

    def test_planted_line_ranges_are_inside_the_fixture(self):
        for t in self.tasks:
            n = len((eb.FIXTURES / t["fixture"]).read_text(
                encoding="utf-8").rstrip("\n").splitlines())
            for d in t["planted"]:
                lo, hi = d["lines"]
                self.assertTrue(1 <= lo <= hi <= n,
                                f"{t['task']}/{d['id']}: range {lo}-{hi} is not "
                                f"inside a {n}-line fixture, so it can never be hit")

    def test_planted_line_ranges_do_not_overlap(self):
        """One citation must not score two defects."""
        for t in self.tasks:
            seen = {}
            for d in t["planted"]:
                lo, hi = d["lines"]
                for n in range(lo, hi + 1):
                    self.assertNotIn(
                        n, seen,
                        f"{t['task']}: line {n} is claimed by both "
                        f"{seen.get(n)} and {d['id']}")
                    seen[n] = d["id"]


class Blindness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = eb.load_tasks()

    def test_prompt_never_carries_the_answer_key(self):
        for t in self.tasks:
            for cond in sorted(eb.CONDITIONS):
                prompt = eb.prompt_for(t, cond)
                self.assertNotIn(t["why"], prompt, t["task"])
                for d in t["planted"]:
                    self.assertNotIn(d["what"], prompt,
                                     f"{t['task']}: prompt describes {d['id']}")
                    self.assertNotIn(d["id"], prompt, t["task"])

    def test_line_numbering_is_uniform(self):
        """Every line is numbered, so numbering marks nothing.

        If only some lines carried numbers, the numbering itself would point at
        the answer.
        """
        for t in self.tasks:
            body = eb.numbered(t).splitlines()
            for i, line in enumerate(body, 1):
                self.assertTrue(line.lstrip().startswith(str(i)),
                                f"{t['task']} line {i} is not numbered")

    def test_numbering_matches_the_real_file(self):
        """A numbering offset would make every honest citation wrong."""
        for t in self.tasks:
            raw = (eb.FIXTURES / t["fixture"]).read_text(
                encoding="utf-8").rstrip("\n").splitlines()
            for i, shown in enumerate(eb.numbered(t).splitlines(), 1):
                self.assertEqual(shown, f"{i:>4}  {raw[i - 1]}", t["task"])


class Conditions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = eb.load_tasks()[0]

    def test_control_delivers_a_different_file(self):
        """The bug that shipped in the first draft: control == treatment."""
        current = eb.prompt_for(self.task, "current")
        flattened = eb.prompt_for(self.task, "flattened")
        self.assertNotEqual(current, flattened)
        self.assertIn("fixtures/flattened/", flattened)
        self.assertNotIn("fixtures/flattened/", current)

    def test_conditions_differ_only_in_the_preamble(self):
        bodies = {eb.prompt_for(self.task, c).split("TASK\n----\n", 1)[1]
                  for c in eb.CONDITIONS}
        self.assertEqual(len(bodies), 1)

    def test_control_files_are_current(self):
        for agent in sorted({t["agent"] for t in eb.load_tasks()}):
            path = eb.flattened_dir() / f"{agent}.md"
            self.assertTrue(path.exists(), f"run --emit-controls for {agent}")
            self.assertEqual(path.read_text(encoding="utf-8"),
                             eb.flattened_text(agent),
                             f"{agent} control is stale; run --emit-controls")

    def test_control_keeps_frontmatter_and_drops_the_body(self):
        agent = self.task["agent"]
        text = eb.flattened_text(agent)
        self.assertIn(f"id: {agent}", text)
        self.assertIn("You are an expert specialist.", text)
        self.assertLess(
            len(text),
            len((REPO_ROOT / eb.agent_path(agent)).read_text(encoding="utf-8")))


class Scoring(unittest.TestCase):
    TASK = {"task": "t", "agent": "engineering-code-reviewer", "fixture": "x",
            "planted": [{"id": "a", "lines": [10, 10], "what": "..."},
                        {"id": "b", "lines": [20, 25], "what": "..."}]}

    def test_a_cited_line_inside_a_range_scores(self):
        r = eb.score_answer(self.TASK, "FINDING: L10: bad\nFINDING: L22: also\nDONE: 2")
        self.assertEqual(sorted(r["found"]), ["a", "b"])
        self.assertEqual(r["missed"], [])

    def test_a_line_outside_every_range_scores_nothing(self):
        r = eb.score_answer(self.TASK, "FINDING: L99: unrelated\nDONE: 1")
        self.assertEqual(r["found"], [])
        self.assertEqual(sorted(r["missed"]), ["a", "b"])

    def test_a_finding_without_a_line_is_not_scoreable(self):
        """The hard edge. Falling back to prose here would restore the old oracle."""
        r = eb.score_answer(self.TASK, "FINDING: line 10 is wrong\nDONE: 1")
        self.assertEqual(r["found"], [])
        self.assertEqual(r["findings_with_a_line"], 0)
        self.assertEqual(r["findings_declared"], 1)

    def test_duplicate_citations_count_once(self):
        r = eb.score_answer(self.TASK, "FINDING: L10: a\nFINDING: L10: again\nDONE: 2")
        self.assertEqual(r["lines_cited"], [10])

    def test_density_punishes_a_scattergun_answer(self):
        """Recall alone would reward citing every line; density is what does not."""
        precise = eb.score_condition(
            [eb.score_answer(self.TASK, "FINDING: L10: a\nFINDING: L20: b\nDONE: 2")])
        scatter = eb.score_condition([eb.score_answer(
            self.TASK,
            "\n".join(f"FINDING: L{n}: maybe" for n in range(1, 31)) + "\nDONE: 30")])
        self.assertEqual(precise["recall_pct"], scatter["recall_pct"])
        self.assertGreater(precise["defect_density"], scatter["defect_density"])

    def test_contract_pct_exposes_unscoreable_answers(self):
        c = eb.score_condition([eb.score_answer(
            self.TASK, "FINDING: L10: a\nFINDING: no line here\nDONE: 2")])
        self.assertEqual(c["findings_declared"], 2)
        self.assertEqual(c["findings_with_a_line"], 1)
        self.assertEqual(c["contract_pct"], 50.0)


class Digest(unittest.TestCase):
    T = [{"task": "t1", "prompt": "p1", "fixture": "b001-orders-report.py",
          "planted": []},
         {"task": "t2", "prompt": "p2", "fixture": "b002-search-handler.py",
          "planted": []}]

    def test_editing_the_answer_key_does_not_invalidate(self):
        changed = [dict(t, planted=[{"id": "x", "lines": [1, 1], "what": "y"}])
                   for t in self.T]
        self.assertEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_editing_a_prompt_invalidates(self):
        changed = [dict(t, prompt="other") if t["task"] == "t1" else t
                   for t in self.T]
        self.assertNotEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_swapping_a_fixture_invalidates(self):
        changed = [dict(t, fixture="b003-task-list.jsx") if t["task"] == "t1"
                   else t for t in self.T]
        self.assertNotEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_changing_the_prompt_template_invalidates(self):
        """The defect the pilot exposed: the template is part of the question."""
        before = eb.tasks_digest(self.T)
        original = eb.PROMPT_TEMPLATE
        try:
            eb.PROMPT_TEMPLATE = original + "\nAlso cite a column number.\n"
            self.assertNotEqual(before, eb.tasks_digest(self.T))
        finally:
            eb.PROMPT_TEMPLATE = original
        self.assertEqual(before, eb.tasks_digest(self.T))

    def test_adding_a_task_leaves_earlier_runs_valid(self):
        grown = self.T + [{"task": "t3", "prompt": "p3",
                           "fixture": "b004-seat-booking.py", "planted": []}]
        answered = ["t1", "t2"]
        self.assertEqual(eb.tasks_digest(self.T, answered),
                         eb.tasks_digest(grown, answered))


class SupersededRuns(unittest.TestCase):
    def test_the_pilot_is_kept_and_excluded_with_a_reason(self):
        """Evidence that invalidated an oracle must not be quietly deleted."""
        path = eb.RESPONSES / "2026-08-16-subagent-pilot12.json"
        self.assertTrue(path.exists(), "the v1 pilot was deleted")
        run = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(run.get("superseded"), "no reason recorded")
        self.assertGreater(len(run["superseded"]), 120,
                           "a superseding reason must actually explain itself")
        scored, superseded = eb.load_runs(eb.load_tasks())
        self.assertIn("2026-08-16-subagent-pilot12",
                      [s["run"] for s in superseded])
        self.assertNotIn("2026-08-16-subagent-pilot12",
                         [r["_name"] for r in scored])

    def test_a_stale_run_without_a_reason_is_still_a_hard_error(self):
        """`superseded` must not become a way to wave through any mismatch.

        Writes a real, non-superseded run with a wrong digest and asserts
        load_runs refuses it. An earlier version of this test raised SystemExit
        itself as a fallback, so it passed whatever the code did -- the vacuous
        pass this project keeps rediscovering.
        """
        tasks = eb.load_tasks()
        probe = eb.RESPONSES / "_zz-probe-not-superseded.json"
        probe.write_text(json.dumps({
            "runner": "test", "model": "test", "recorded_at": "2026-01-01",
            "tasks_sha256": "0" * 64,
            "answers": {"none": {tasks[0]["task"]: "FINDING: L1: x\nDONE: 1"}},
        }), encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as ctx:
                eb.load_runs(tasks)
            self.assertIn("_zz-probe-not-superseded", str(ctx.exception))
        finally:
            probe.unlink()
        # and the suite is left clean
        eb.load_runs(tasks)


class Report(unittest.TestCase):
    def test_report_is_byte_stable(self):
        from lib.corpus import dump_json
        self.assertEqual(dump_json(eb.build_report()), dump_json(eb.build_report()))

    def test_superseded_runs_are_visible_in_the_report(self):
        self.assertTrue(eb.build_report()["superseded_runs"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
