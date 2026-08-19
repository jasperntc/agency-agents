#!/usr/bin/env python3
"""Tests for scripts/eval_behaviour.py.

Two pilots invalidated two oracles here, so these assert the properties whose
absence made each failure possible.

  WINDOWS ARE DECLARED    The v2 pilot scored three correct diagnoses as misses
                          purely on attribution -- a race cited at the line
                          where the count is taken rather than compared. Every
                          defect now declares its own tolerance, explicitly.
  MATCHING, NOT LOOKUP    Windows must overlap (b004's race and row-count both
                          centre on L21), so scoring assigns each finding to at
                          most one defect. Independent lookup would let one
                          vague finding score both.
  THE CONTROL IS A CONTROL  `flattened` must deliver a different file from
                          `current`. It did not in the first draft.
  IDENTICAL DELIVERY      Conditions differ only in the agent file.
  DIGEST COVERS THE PROMPT  The v1 pilot was answered under a template that
                          never asked for lines. A digest blind to the template
                          would have let those answers be re-scored by an oracle
                          they could not satisfy.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_behaviour as eb  # noqa: E402

NL = "\n"


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
                encoding="utf-8").rstrip(NL).splitlines())
            for d in t["planted"]:
                self.assertTrue(d["lines"], f"{t['task']}/{d['id']}: no anchors")
                for lo, hi in d["lines"]:
                    self.assertTrue(1 <= lo <= hi <= n,
                                    f"{t['task']}/{d['id']}: range {lo}-{hi} is "
                                    f"not inside a {n}-line fixture, so it can "
                                    f"never be hit")

    REQUIRED_TIERS = ("easy", "hard", "niche")

    def test_the_required_tiers_exist_and_are_not_thin(self):
        """An easy-only benchmark cannot separate anything -- the v2 pilot put
        three of four tasks at full recall in every condition.

        `hard` answers 'is the defect obscure enough'; the hard tier still found
        nothing, because a strong model saturates code review whatever it is
        given. `niche` answers a different question -- 'is the DOMAIN one the
        base model knows less about' -- which is the only remaining place an
        agent file could plausibly add something.

        Every tier must carry at least four tasks. A tier of one or two is a
        sampling accident dressed as a dimension.
        """
        counts = {tier: sum(1 for t in self.tasks if t.get("tier") == tier)
                  for tier in self.REQUIRED_TIERS}
        for tier, n in counts.items():
            self.assertGreaterEqual(n, 4, f"{tier} tier has only {n} tasks")
        self.assertFalse(
            [t["task"] for t in self.tasks
             if t.get("tier") not in self.REQUIRED_TIERS],
            "a task carries an unrecognised tier; add it to REQUIRED_TIERS "
            "deliberately rather than letting tiers accumulate")

    def test_every_defect_declares_its_window(self):
        """Overlap is intentional now; the tolerance must still be chosen.

        A defaulted window is a scoring decision nobody made. Capped at 2
        because beyond that it stops being attribution tolerance and starts
        crediting a finding for pointing near the right area.
        """
        for t in self.tasks:
            for d in t["planted"]:
                self.assertIn("window", d,
                              f"{t['task']}/{d['id']}: window must be explicit")
                self.assertLessEqual(d["window"], 2, f"{t['task']}/{d['id']}")


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
        """Every line is numbered, so the numbering marks nothing."""
        for t in self.tasks:
            for i, line in enumerate(eb.numbered(t).splitlines(), 1):
                self.assertTrue(line.lstrip().startswith(str(i)),
                                f"{t['task']} line {i} is not numbered")

    def test_numbering_matches_the_real_file(self):
        """An offset would make every honest citation wrong."""
        for t in self.tasks:
            raw = (eb.FIXTURES / t["fixture"]).read_text(
                encoding="utf-8").rstrip(NL).splitlines()
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
        bodies = {eb.prompt_for(self.task, c).split("TASK" + NL + "----" + NL, 1)[1]
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


def answer(*findings: str) -> str:
    """Build an answer body without embedding escapes in a heredoc."""
    return NL.join(list(findings) + [f"DONE: {len(findings)}"])


class Scoring(unittest.TestCase):
    TASK = {"task": "t", "agent": "engineering-code-reviewer", "fixture": "x",
            "planted": [{"id": "a", "lines": [[10, 10]], "window": 1, "what": ""},
                        {"id": "b", "lines": [[20, 25]], "window": 1, "what": ""}]}
    # Deliberately overlapping, like b004's race and its row-count.
    OVERLAP = {"task": "o", "agent": "x", "fixture": "x",
               "planted": [{"id": "race", "lines": [[21, 27]], "window": 1, "what": ""},
                           {"id": "count", "lines": [[21, 21]], "window": 0, "what": ""}]}

    def test_a_cited_line_inside_a_range_scores(self):
        r = eb.score_answer(self.TASK, answer("FINDING: L10: x", "FINDING: L22: y"))
        self.assertEqual(sorted(r["found"]), ["a", "b"])

    def test_the_window_forgives_adjacent_attribution(self):
        """The v2 failure: a race keyed at L22 was cited at L21 by everyone."""
        r = eb.score_answer(self.TASK, answer("FINDING: L9: just outside"))
        self.assertEqual(r["found"], ["a"])

    def test_the_window_is_not_unbounded(self):
        r = eb.score_answer(self.TASK, answer("FINDING: L15: far off"))
        self.assertEqual(r["found"], [])

    def test_two_findings_on_one_line_can_score_two_defects(self):
        """b004/none filed a race and a row-count both at L21. Both are real."""
        r = eb.score_answer(
            self.OVERLAP, answer("FINDING: L21: race", "FINDING: L21: rows"))
        self.assertEqual(sorted(r["found"]), ["count", "race"])

    def test_one_finding_on_that_line_scores_only_one(self):
        """The other half. Independent lookup would credit both here."""
        r = eb.score_answer(self.OVERLAP, answer("FINDING: L21: something"))
        self.assertEqual(len(r["found"]), 1)

    def test_a_defect_may_declare_several_anchors(self):
        """A wall-clock timeout lives both where the stamp is taken and where it
        is compared. Declaring one and calling the other a miss is what
        manufactured the v2 pilot's phantom separation."""
        two = {"task": "m", "agent": "x", "fixture": "x",
               "planted": [{"id": "clock", "lines": [[19, 19], [31, 31]],
                            "window": 1, "what": ""}]}
        self.assertEqual(
            eb.score_answer(two, answer("FINDING: L19: wall clock"))["found"],
            ["clock"])
        self.assertEqual(
            eb.score_answer(two, answer("FINDING: L31: wall clock"))["found"],
            ["clock"])
        self.assertEqual(
            eb.score_answer(two, answer("FINDING: L25: unrelated"))["found"], [])

    def test_a_finding_without_a_line_is_not_scoreable(self):
        r = eb.score_answer(self.TASK, answer("FINDING: line 10 is wrong"))
        self.assertEqual(r["found"], [])
        self.assertEqual(r["findings_with_a_line"], 0)
        self.assertEqual(r["findings_declared"], 1)

    def test_lines_cited_deduplicates_but_scoring_does_not(self):
        r = eb.score_answer(
            self.OVERLAP, answer("FINDING: L21: a", "FINDING: L21: b"))
        self.assertEqual(r["lines_cited"], [21])
        self.assertEqual(r["findings_with_a_line"], 2)
        self.assertEqual(len(r["found"]), 2)

    def test_density_punishes_a_scattergun_answer(self):
        precise = eb.score_condition([eb.score_answer(
            self.TASK, answer("FINDING: L10: a", "FINDING: L20: b"))])
        scatter = eb.score_condition([eb.score_answer(
            self.TASK, answer(*[f"FINDING: L{n}: maybe" for n in range(1, 31)]))])
        self.assertEqual(precise["recall_pct"], scatter["recall_pct"])
        self.assertGreater(precise["defect_density"], scatter["defect_density"])

    def test_contract_pct_exposes_unscoreable_answers(self):
        c = eb.score_condition([eb.score_answer(
            self.TASK, answer("FINDING: L10: a", "FINDING: no line here"))])
        self.assertEqual(c["contract_pct"], 50.0)


class Digest(unittest.TestCase):
    T = [{"task": "t1", "prompt": "p1", "fixture": "b001-orders-report.py",
          "planted": []},
         {"task": "t2", "prompt": "p2", "fixture": "b002-search-handler.py",
          "planted": []}]

    def test_editing_the_answer_key_does_not_invalidate(self):
        """What let the v2 answers be re-scored under a fixed oracle, free."""
        changed = [dict(t, planted=[{"id": "x", "lines": [[1, 1]], "window": 1,
                                     "what": "y"}]) for t in self.T]
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
        """The v1 defect: the template is part of the question."""
        before = eb.tasks_digest(self.T)
        original = eb.PROMPT_TEMPLATE
        try:
            eb.PROMPT_TEMPLATE = original + "Also cite a column." + NL
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
    def test_the_v1_pilot_is_kept_and_excluded_with_a_reason(self):
        """Evidence that invalidated an oracle must not be quietly deleted."""
        path = eb.RESPONSES / "2026-08-16-subagent-pilot12.json"
        self.assertTrue(path.exists(), "the v1 pilot was deleted")
        run = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreater(len(run.get("superseded", "")), 120,
                           "a superseding reason must explain itself")
        scored, superseded = eb.load_runs(eb.load_tasks())
        self.assertIn("2026-08-16-subagent-pilot12",
                      [s["run"] for s in superseded])
        self.assertNotIn("2026-08-16-subagent-pilot12",
                         [r["_name"] for r in scored])

    def test_a_stale_run_without_a_reason_is_still_a_hard_error(self):
        """`superseded` must not become a way to wave through any mismatch.

        Writes a real non-superseded run with a wrong digest. An earlier version
        raised SystemExit itself as a fallback, so it passed whatever the code
        did -- the vacuous pass this project keeps rediscovering.
        """
        tasks = eb.load_tasks()
        probe = eb.RESPONSES / "_zz-probe-not-superseded.json"
        probe.write_text(json.dumps({
            "runner": "test", "model": "test", "recorded_at": "2026-01-01",
            "tasks_sha256": "0" * 64,
            "answers": {"none": {tasks[0]["task"]: "FINDING: L1: x"}},
        }), encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as ctx:
                eb.load_runs(tasks)
            self.assertIn("_zz-probe-not-superseded", str(ctx.exception))
        finally:
            probe.unlink()
        eb.load_runs(tasks)


class Report(unittest.TestCase):
    def test_report_is_byte_stable(self):
        from lib.corpus import dump_json
        self.assertEqual(dump_json(eb.build_report()), dump_json(eb.build_report()))

    def test_superseded_runs_are_visible_in_the_report(self):
        self.assertTrue(eb.build_report()["superseded_runs"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
