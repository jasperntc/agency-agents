#!/usr/bin/env python3
"""Tests for scripts/eval_behaviour.py.

The instrument is new, and on this project's record a new instrument's first
run is wrong in a way that looks like a result: the routing harness counted 271
agents in a 270-agent corpus, the promotion suite passed vacuously in CI, and
the selection pilot's 100% came from a sample that removed the hard half of the
problem. So the properties that would make a behavioural score meaningless are
asserted here before any answer is collected.

Four of them matter more than the rest:

  ANTI-TAUTOLOGY   If a fixture or prompt contains the words that score a hit,
                   the task is solved by reading it back and every condition
                   scores the same. This is the behavioural analogue of the
                   token-overlap leakage check in the routing harness.
  THE CONTROL IS A CONTROL  `flattened` must deliver a DIFFERENT file from
                   `current`. It did not, in the first draft of the harness --
                   both preambles pointed at the real agent -- which would have
                   produced a perfectly clean null result meaning nothing.
  IDENTICAL DELIVERY  Conditions must differ ONLY in the agent file. If one gets
                   a path and another gets inline text, the comparison measures
                   the prompt.
  DIGEST RULES     A run is bound to the question asked, not the answer key.
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

    def test_there_are_tasks(self):
        self.assertTrue(self.tasks)

    def test_task_ids_are_unique(self):
        ids = [t["task"] for t in self.tasks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_agent_exists(self):
        for t in self.tasks:
            self.assertTrue((REPO_ROOT / eb.agent_path(t["agent"])).exists(),
                            f"{t['task']}: no such agent {t['agent']}")

    def test_every_fixture_exists(self):
        for t in self.tasks:
            self.assertTrue((eb.FIXTURES / t["fixture"]).exists(), t["task"])

    def test_every_task_has_planted_and_clean(self):
        """Without `clean`, recall is unbounded and padding the answer wins."""
        for t in self.tasks:
            self.assertTrue(t["planted"], f"{t['task']}: no planted defects")
            self.assertTrue(t["clean"],
                            f"{t['task']}: no clean aspects, so false claims "
                            f"cannot be measured and `lift` is just recall")


class AntiTautology(unittest.TestCase):
    """The scoring phrases must not be readable off the question."""

    @classmethod
    def setUpClass(cls):
        cls.tasks = eb.load_tasks()

    def question(self, task: dict) -> str:
        return (task["prompt"] + "\n"
                + (eb.FIXTURES / task["fixture"]).read_text(encoding="utf-8"))

    def test_no_planted_phrasing_appears_in_the_prompt_or_fixture(self):
        """Asserted through eb.matched(), so it tests what the SCORER can see.

        Checking with a plain substring here would make the test stricter than
        the scorer and would reject phrases the scorer handles correctly. The
        property that matters is 'the scorer cannot score a hit by quoting the
        question back', which is a statement about eb.matched().
        """
        for t in self.tasks:
            haystack = self.question(t)
            for defect in t["planted"]:
                hit = eb.matched(haystack, defect["any_of"])
                self.assertIsNone(
                    hit,
                    f"{t['task']}: the phrase {hit!r} that scores "
                    f"{defect['id']} is readable off the question itself. Any "
                    f"answer that quotes the file scores a hit.")

    def test_no_clean_phrasing_appears_in_the_prompt_or_fixture(self):
        """Symmetric: a false claim must not be scoreable by quoting either."""
        for t in self.tasks:
            self.assertIsNone(
                eb.matched(self.question(t),
                           [p for c in t["clean"] for p in c["any_of"]]),
                t["task"])

    def test_planted_and_clean_phrasings_do_not_overlap(self):
        """One sentence must not be able to score as both a hit and a miss."""
        for t in self.tasks:
            planted = {p.lower() for d in t["planted"] for p in d["any_of"]}
            clean = {p.lower() for c in t["clean"] for p in c["any_of"]}
            self.assertEqual(planted & clean, set(), t["task"])


class Conditions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = eb.load_tasks()
        cls.task = cls.tasks[0]

    def test_control_delivers_a_different_file(self):
        """The bug this test exists for shipped in the first draft.

        Both `current` and `flattened` formatted the same agent path, so the
        positive control was the treatment. It would have produced a clean null
        result -- 'the flattened agent scores the same' -- that meant nothing.
        """
        current = eb.prompt_for(self.task, "current")
        flattened = eb.prompt_for(self.task, "flattened")
        self.assertNotEqual(current, flattened)
        self.assertIn("fixtures/flattened/", flattened)
        self.assertNotIn("fixtures/flattened/", current)

    def test_conditions_differ_only_in_the_agent_file(self):
        """Everything after the preamble must be byte-identical."""
        bodies = set()
        for cond in ("none", "current", "candidate", "flattened"):
            prompt = eb.prompt_for(self.task, cond)
            bodies.add(prompt.split("TASK\n----\n", 1)[1])
        self.assertEqual(len(bodies), 1,
                         "conditions differ somewhere other than the preamble")

    def test_no_condition_names_the_defect(self):
        """The prompt must not coach. It would measure this file, not the agent."""
        for cond in sorted(eb.CONDITIONS):
            prompt = eb.prompt_for(self.task, cond).lower()
            for defect in self.task["planted"]:
                for phrase in defect["any_of"]:
                    self.assertNotIn(phrase.lower(), prompt, f"{cond}")

    def test_control_files_are_current(self):
        """Committed derived artifact, same lockfile rule as everywhere here."""
        for agent in sorted({t["agent"] for t in self.tasks}):
            path = eb.flattened_dir() / f"{agent}.md"
            self.assertTrue(path.exists(),
                            f"missing control for {agent}; run --emit-controls")
            self.assertEqual(
                path.read_text(encoding="utf-8"), eb.flattened_text(agent),
                f"{agent} control is stale. Run "
                f"./scripts/eval_behaviour.py --emit-controls")

    def test_control_keeps_the_frontmatter_and_drops_the_body(self):
        """A malformed control would drop the score for the wrong reason."""
        agent = self.task["agent"]
        text = eb.flattened_text(agent)
        real = (REPO_ROOT / eb.agent_path(agent)).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"))
        self.assertIn(f"id: {agent}", text)
        self.assertIn("You are an expert specialist.", text)
        self.assertLess(len(text), len(real),
                        "the control is not shorter than the real agent")


class Scoring(unittest.TestCase):
    TASK = {
        "task": "t1", "agent": "engineering-code-reviewer", "fixture": "x",
        "planted": [{"id": "a", "any_of": ["alpha"]},
                    {"id": "b", "any_of": ["bravo", "brava"]}],
        "clean": [{"id": "c", "any_of": ["charlie"]}],
    }

    def test_finds_planted_and_ignores_case(self):
        r = eb.score_answer(self.TASK, "FINDING: ALPHA is wrong here")
        self.assertEqual(r["found"], ["a"])
        self.assertEqual(r["missed"], ["b"])
        self.assertEqual(r["false_claims"], [])

    def test_any_of_is_an_alternation(self):
        self.assertEqual(eb.score_answer(self.TASK, "brava")["found"], ["b"])

    def test_a_phrase_inside_a_longer_word_is_not_a_match(self):
        """The `SQLi` in `sqlite3` case, pinned so it cannot come back."""
        self.assertIsNone(eb.matched("we use sqlite3 here", ["SQLi"]))
        self.assertEqual(eb.matched("this is SQLi, plainly", ["SQLi"]), "SQLi")

    def test_phrases_ending_in_punctuation_still_match(self):
        """A blanket \\b...\\b would make these silently never fire."""
        self.assertEqual(eb.matched("use qs.aggregate(...)", [".aggregate"]),
                         ".aggregate")
        self.assertEqual(eb.matched("you pass key={index} here", ["key={index}"]),
                         "key={index}")

    def test_claiming_clean_code_is_a_false_claim(self):
        r = eb.score_answer(self.TASK, "FINDING: charlie is broken")
        self.assertEqual(r["false_claims"], ["c"])

    def test_findings_are_counted(self):
        answer = "FINDING: one\nFINDING: two\nDONE: 2"
        self.assertEqual(eb.score_answer(self.TASK, answer)["findings_reported"], 2)

    def test_lift_is_recall_minus_false_claims(self):
        """Padding must not pay. The whole point of scoring `clean`."""
        rows = [eb.score_answer(self.TASK, "alpha bravo charlie")]
        c = eb.score_condition(rows)
        self.assertEqual(c["found_pct"], 100.0)
        self.assertEqual(c["false_pct"], 100.0)
        self.assertEqual(c["lift"], 0.0)

    def test_a_perfect_answer_scores_full_lift(self):
        c = eb.score_condition([eb.score_answer(self.TASK, "alpha bravo")])
        self.assertEqual(c["lift"], 100.0)

    def test_an_empty_answer_scores_zero_not_negative(self):
        c = eb.score_condition([eb.score_answer(self.TASK, "")])
        self.assertEqual((c["found_pct"], c["false_pct"], c["lift"]),
                         (0.0, 0.0, 0.0))


class Digest(unittest.TestCase):
    T = [{"task": "t1", "prompt": "p1", "fixture": "b001-orders-report.py",
          "planted": [], "clean": []},
         {"task": "t2", "prompt": "p2", "fixture": "b002-search-handler.py",
          "planted": [], "clean": []}]

    def test_editing_the_answer_key_does_not_invalidate_a_run(self):
        changed = [dict(t, planted=[{"id": "x", "any_of": ["y"]}]) for t in self.T]
        self.assertEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_editing_a_prompt_invalidates(self):
        changed = [dict(t, prompt="different") if t["task"] == "t1" else t
                   for t in self.T]
        self.assertNotEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_swapping_a_fixture_invalidates(self):
        """The fixture is half the question, so its bytes are in the digest."""
        changed = [dict(t, fixture="b003-task-list.jsx") if t["task"] == "t1"
                   else t for t in self.T]
        self.assertNotEqual(eb.tasks_digest(self.T), eb.tasks_digest(changed))

    def test_adding_a_task_leaves_earlier_runs_valid(self):
        grown = self.T + [{"task": "t3", "prompt": "p3",
                           "fixture": "b004-seat-booking.py",
                           "planted": [], "clean": []}]
        answered = ["t1", "t2"]
        self.assertEqual(eb.tasks_digest(self.T, answered),
                         eb.tasks_digest(grown, answered))

    def test_digest_is_order_independent(self):
        self.assertEqual(eb.tasks_digest(self.T),
                         eb.tasks_digest(list(reversed(self.T))))


class Report(unittest.TestCase):
    def test_builds_with_no_runs(self):
        r = eb.build_report()
        self.assertEqual(r["tasks"]["total"], len(eb.load_tasks()))
        self.assertIn("none", r["conditions"])

    def test_report_is_byte_stable(self):
        from lib.corpus import dump_json
        self.assertEqual(dump_json(eb.build_report()), dump_json(eb.build_report()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
