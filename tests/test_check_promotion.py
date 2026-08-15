#!/usr/bin/env python3
"""Regression tests for the promotion gate.

    python3 tests/test_check_promotion.py

The question this file exists to answer is not "does the code run". It is:

    Would this gate have stopped the one regression we know about?

archive/fable-upgrade rewrote 263 of 264 agents while every check of the day
passed, and corpus-level maximum pairwise similarity moved 0.0113 points across
it. test_would_have_caught_the_fable_upgrade replays that change through the
per-agent rules. Its companion, test_absolute_ceiling_alone_catches_nothing,
shows the absolute similarity ceiling still catching zero of them -- so the
deltas are demonstrably doing the work, not riding along beside a bound that
would have fired anyway.

The other half is false positives. A gate that blocks ordinary contributions
gets switched off, so test_real_upstream_edit_does_not_fire replays a genuine
10-file upstream security fix and requires silence.

Requires git refs `archive/fable-upgrade` and the upstream history. Nothing is
checked out; blobs stream through `git cat-file`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_promotion as cp  # noqa: E402

KNOWN_BAD = "archive/fable-upgrade"
KNOWN_BAD_BASE = "459dce8"

# Real agent changes from this repository's history, chosen because nobody
# involved was thinking about this gate when they made them. 11 agents added and
# 65 modified between them. The header-normalization commit is the hardest case
# on purpose: rewriting section headings toward a common form is precisely the
# kind of edit that pushes agents to look alike, and it still must pass.
CLEAN_EDITS = (
    ("9f3e401", "normalize section headers across 15 agents"),
    ("86a6695", "add 6 specialists"),
    ("e4a0fbc", "add a missing trailing newline to 48 agents"),
    ("c89557f", "add Economy Designer, improve Reality Checker"),
    ("8ef4923", "add 4 gated single agents"),
)

THRESHOLDS = json.loads(
    (REPO_ROOT / "metrics" / "promotion-thresholds.json").read_bytes().decode("utf-8"))
RULES = THRESHOLDS["thresholds"]


def git(args: list[str]) -> str:
    return subprocess.run(["git"] + args, cwd=REPO_ROOT,
                          capture_output=True).stdout.decode("utf-8", "replace")


def changed_between(base: str, head: str) -> dict[str, list[str]]:
    """The same shape changed_agents() produces, for two arbitrary refs."""
    in_head = set(cp.read_corpus(head))
    in_base = set(cp.read_corpus(base))
    out: dict[str, list[str]] = {"added": [], "modified": [], "removed": []}
    for line in git(["diff", "--name-status", base, head, "--"]).splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        if path not in in_head and path not in in_base:
            continue
        if status.startswith("A"):
            out["added"].append(path)
        elif status.startswith("D"):
            out["removed"].append(path)
        elif status.startswith(("M", "R", "C")):
            out["modified"].append(path)
    return {k: sorted(v) for k, v in out.items()}


class DetectsTheKnownRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.changed = changed_between(KNOWN_BAD_BASE, KNOWN_BAD)
        cls.failures, cls.advisories, cls.rows = cp.review_agents(
            cls.changed, KNOWN_BAD_BASE, RULES, head_ref=KNOWN_BAD)
        cls.base_metrics = cp.agent_metrics(KNOWN_BAD_BASE)
        cls.bad_metrics = cp.agent_metrics(KNOWN_BAD)

    def test_would_have_caught_the_fable_upgrade(self):
        self.assertGreaterEqual(
            len(self.failures), 20,
            "The per-agent gate must fire on a real 263-file homogenization. "
            "If this drops, the thresholds have been loosened past usefulness.",
        )

    def test_absolute_ceiling_alone_catches_nothing(self):
        """NEGATIVE CONTROL: the max-similarity bound sees none of it.

        This is the same statistic scripts/check-agent-originality.sh gates on.
        Every failure above therefore comes from a DELTA, which is the whole
        argument for comparing an agent against its own previous self.
        """
        cap = RULES["agent.max_similarity_pct"]["max"]
        over = [p for p, m in self.bad_metrics.items()
                if m["max_similarity_pct"] > cap]
        self.assertEqual(over, [], "the absolute ceiling was expected to be blind")

    def test_growth_is_advisory_not_a_failure(self):
        """The known-bad change grew agents by +11% median, +219% at worst.

        None of that may fail a build. Length is a cost to be justified, and a
        gate that blocks a longer agent blocks legitimate rewrites too.
        """
        self.assertTrue(self.advisories, "expected growth advisories on this ref")
        for f in self.failures:
            self.assertNotIn("longer", f)

    def test_recorded_calibration_matches_reality(self):
        """Every number in the calibration block is re-measured, not trusted."""
        cal = THRESHOLDS["calibration"]
        common = sorted(set(self.base_metrics) & set(self.bad_metrics))
        self.assertEqual(cal["agents_caught_at_current_thresholds"]["of_total"],
                         len(common))

        dsim = sum(1 for p in common
                   if self.bad_metrics[p]["max_similarity_pct"]
                   - self.base_metrics[p]["max_similarity_pct"] > 1.0)
        ddup = sum(1 for p in common
                   if self.bad_metrics[p]["duplicated_word_pct"]
                   - self.base_metrics[p]["duplicated_word_pct"] > 2.0)
        caught = cal["agents_caught_at_current_thresholds"]
        self.assertEqual(caught["max_similarity_delta_over_1.0"], dsim)
        self.assertEqual(caught["duplicated_word_delta_over_2.0"], ddup)

        self.assertEqual(cal["clean_corpus_absolute"]["duplicated_word_pct"]["max"],
                         max(m["duplicated_word_pct"]
                             for m in cp.agent_metrics(None).values()))

    def test_absolute_duplicate_ceiling_sits_between_clean_and_known_bad(self):
        """The one threshold here that CAN be bracketed, is."""
        rule = RULES["agent.duplicated_word_pct"]
        self.assertLess(rule["observed_clean_max"], rule["max"])
        self.assertLess(rule["max"], rule["observed_known_bad_max"])


class DoesNotFireOnOrdinaryWork(unittest.TestCase):
    """False-positive calibration. A gate that blocks ordinary contributions is
    a gate that gets switched off, and then the regression it was built for
    walks straight through it."""

    def test_real_agent_changes_do_not_fire(self):
        touched = 0
        for commit, what in CLEAN_EDITS:
            with self.subTest(commit=commit, change=what):
                changed = changed_between(f"{commit}^", commit)
                n = len(changed["added"]) + len(changed["modified"])
                self.assertTrue(n, f"expected agent files in {commit}")
                touched += n
                failures, _, _ = cp.review_agents(
                    changed, f"{commit}^", RULES, head_ref=commit)
                self.assertEqual(failures, [], f"fired on: {what}")
        self.assertGreaterEqual(touched, 70, "false-positive sample got smaller")


class Ratchet(unittest.TestCase):
    """D6. Thresholds may be tightened freely and never loosened silently."""

    BEFORE = {"thresholds": {
        "a.metric": {"max": 10.0},
        "b.metric": {"min": 50.0},
    }}

    def compare(self, after: dict):
        return cp.compare_thresholds("metrics/x.json", self.BEFORE, after)

    def test_raising_a_max_fails(self):
        failures, released = self.compare(
            {"thresholds": {"a.metric": {"max": 20.0}, "b.metric": {"min": 50.0}}})
        self.assertEqual(len(failures), 1)
        self.assertEqual(released, [])
        self.assertIn("10.0 -> 20.0", failures[0])

    def test_lowering_a_min_fails(self):
        failures, _ = self.compare(
            {"thresholds": {"a.metric": {"max": 10.0}, "b.metric": {"min": 5.0}}})
        self.assertEqual(len(failures), 1)
        self.assertIn("50.0 -> 5.0", failures[0])

    def test_deleting_a_threshold_fails(self):
        failures, _ = self.compare({"thresholds": {"a.metric": {"max": 10.0}}})
        self.assertEqual(len(failures), 1)
        self.assertIn("was removed", failures[0])

    def test_deleting_the_whole_block_fails_every_entry(self):
        failures, _ = self.compare({"thresholds": {}})
        self.assertEqual(len(failures), 2)

    def test_tightening_passes(self):
        failures, released = self.compare(
            {"thresholds": {"a.metric": {"max": 4.0}, "b.metric": {"min": 90.0}}})
        self.assertEqual((failures, released), ([], []))

    def test_adding_a_threshold_passes(self):
        failures, _ = self.compare({"thresholds": {
            "a.metric": {"max": 10.0}, "b.metric": {"min": 50.0},
            "c.metric": {"max": 1.0}}})
        self.assertEqual(failures, [])

    def test_a_written_reason_releases_the_ratchet(self):
        """Deliberate loosening is allowed. Silent loosening is not.

        The escape hatch is the point: a ratchet with no release gets bypassed
        by deleting the check instead, and that is worse. This one costs a
        sentence, and the sentence lands in the diff.
        """
        failures, released = self.compare({"thresholds": {
            "a.metric": {"max": 20.0,
                         "loosened_why": "corpus doubled; measured on the new set"},
            "b.metric": {"min": 50.0}}})
        self.assertEqual(failures, [])
        self.assertEqual(len(released), 1)
        self.assertIn("corpus doubled", released[0])

    def test_a_stale_reason_does_not_release_it_twice(self):
        """A justification already present in the base cannot excuse a NEW move.

        Otherwise one `loosened_why` written once would license every future
        loosening of that threshold forever.
        """
        before = {"thresholds": {"a.metric": {"max": 10.0, "loosened_why": "old"}}}
        failures, released = cp.compare_thresholds(
            "metrics/x.json", before,
            {"thresholds": {"a.metric": {"max": 30.0, "loosened_why": "old"}}})
        self.assertEqual(len(failures), 1)
        self.assertEqual(released, [])

    def test_every_thresholds_file_is_ratcheted(self):
        """A new gate must be added to RATCHETED or it is unguarded.

        Forgetting is silent otherwise: the gate works, and its thresholds can
        be edited downward at will.
        """
        on_disk = {p.relative_to(REPO_ROOT).as_posix()
                   for p in (REPO_ROOT / "metrics").glob("*thresholds*.json")}
        self.assertEqual(
            on_disk - set(cp.RATCHETED), set(),
            "threshold file(s) not listed in check_promotion.RATCHETED",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
