#!/usr/bin/env python3
"""The description-proposal gate has to be able to say no.

WHY THIS FILE IS MOSTLY ABOUT REJECTION

A gate that accepts everything put in front of it is not a gate, and this
repository has shipped five green checks that measured nothing. So the load
bearing assertions here are the negative ones: the calibration proposals, which
are written to be unacceptable, must be rejected, and the gate's first version
-- which counted phrase collisions only -- passed both of them. That failure is
the reason the measure counts distinct cases instead, and this file exists so it
cannot silently regress to something that agrees with everything.

WHAT A PROPOSAL MAY NOT DO

Change anything except a description. The 270 filename stems, ids and `name`
values are load-bearing identity and are never renamed, so a proposals file
carrying any of those fields is a category error rather than a bad suggestion.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pd = _load("propose_descriptions", "scripts/propose_descriptions.py")
er = _load("eval_routing_for_proposals", "scripts/eval_routing.py")

REQUIRED = ("id", "agent", "targets", "proposed", "source", "observed",
            "recorded_at")
FORBIDDEN = ("name", "stem", "filename", "new_id", "rename")


class ProposalSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposals = pd.load_proposals()
        cls.calibration = pd.load_proposals(pd.CALIBRATION)
        cls.ids = {e["id"] for e in er.load_index()}

    def test_every_proposal_has_the_required_fields(self):
        for p in self.proposals + self.calibration:
            for field in REQUIRED:
                self.assertIn(field, p, f"{p.get('id')} lacks {field}")

    def test_proposal_ids_are_unique(self):
        ids = [p["id"] for p in self.proposals + self.calibration]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_proposal_names_a_real_agent(self):
        for p in self.proposals + self.calibration:
            self.assertIn(p["agent"], self.ids,
                          f"{p['id']} targets an agent not in the index")

    def test_no_proposal_tries_to_rename_anything(self):
        """Stems, ids and name values are identity and are never renamed."""
        for p in self.proposals + self.calibration:
            for field in FORBIDDEN:
                self.assertNotIn(
                    field, p,
                    f"{p['id']} carries {field!r}. A proposal may change a "
                    f"description and nothing else.")

    def test_every_proposal_says_where_it_came_from(self):
        for p in self.proposals + self.calibration:
            self.assertIn(p["source"], pd.SOURCES, p["id"])
            self.assertTrue(p["observed"].strip(),
                            f"{p['id']} does not say what prompted it")

    def test_a_proposal_actually_changes_the_description(self):
        current = {e["id"]: e["description"] for e in er.load_index()}
        for p in self.proposals + self.calibration:
            self.assertNotEqual(
                p["proposed"].strip(), current[p["agent"]].strip(),
                f"{p['id']} proposes the description that already ships")


class TheGateCanSayNo(unittest.TestCase):
    """The two-sided property. Without it an ACCEPT means nothing."""

    @classmethod
    def setUpClass(cls):
        cls.entries = er.load_index()
        cls.cases = er.load_cases()

    def _score(self, proposal):
        return pd.score(proposal, self.entries, self.cases)

    def test_the_calibration_set_is_not_empty(self):
        self.assertTrue(pd.load_proposals(pd.CALIBRATION),
                        "no deliberately-bad proposals: the gate is unverified")

    def test_every_calibration_proposal_is_rejected(self):
        for p in pd.load_proposals(pd.CALIBRATION):
            result = self._score(p)
            self.assertEqual(
                "REJECT", result["verdict"],
                f"{p['id']} was written to be unacceptable and the gate "
                f"accepted it: {result}")

    def test_calibration_proposals_do_reach_their_target(self):
        """They must fail on COST, not by being broken.

        A calibration proposal that reached nothing would be rejected for the
        wrong reason and would prove nothing about the gate's ability to price
        collateral damage.
        """
        for p in pd.load_proposals(pd.CALIBRATION):
            self.assertTrue(
                self._score(p)["gained"],
                f"{p['id']} reaches no new case, so its rejection says nothing "
                f"about whether the gate can price over-widening")

    def test_an_accepted_proposal_wins_at_least_as_much_as_it_costs(self):
        for p in pd.load_proposals():
            r = self._score(p)
            if r["verdict"] != "ACCEPT":
                continue
            self.assertTrue(r["gained"])
            self.assertEqual([], r["lost"])
            self.assertLessEqual(len(r["attracted"]), len(r["gained"]))

    def test_a_description_that_reaches_nothing_new_is_rejected(self):
        """The trivial no-op case, asserted rather than assumed."""
        agent = self.entries[0]["id"]
        noop = {"id": "zz-noop", "agent": agent, "targets": [],
                "proposed": "A specialist.", "source": "measured-gap",
                "observed": "probe", "recorded_at": "2026-08-20"}
        self.assertEqual("REJECT", self._score(noop)["verdict"])

    def test_counting_phrases_alone_would_have_passed_the_bad_ones(self):
        """The regression this file exists for.

        The gate's first version counted adjacent-phrase collisions only, and
        both calibration proposals went straight through it. If `reaches` ever
        narrows back to phrases, this fails.
        """
        import re
        bad = pd.load_proposals(pd.CALIBRATION)[0]
        after = pd.swap(self.entries, bad["agent"], bad["proposed"])
        phrase_only, full = 0, 0
        for case in self.cases:
            if bad["agent"] in (case.get("expect") or []):
                continue
            _, phrases = er.candidates(case["task"])
            singles, _ = er.candidates(case["task"])
            was_p = any(bad["agent"] in er.matches(q, self.entries)
                        for q in phrases)
            now_p = any(bad["agent"] in er.matches(q, after) for q in phrases)
            phrase_only += int(now_p and not was_p)
            was_f = pd.reaches(case["task"], self.entries, bad["agent"])
            now_f = pd.reaches(case["task"], after, bad["agent"])
            full += int(now_f and not was_f)
        self.assertGreater(
            full, phrase_only,
            "counting whole-query reach no longer sees more collateral than "
            "counting phrases alone -- the calibration failure that motivated "
            "this measure would not be caught again")


class Baseline(unittest.TestCase):
    def test_the_committed_baseline_matches(self):
        from lib.corpus import dump_json  # noqa: E402
        if not pd.BASELINE.exists():
            self.skipTest("no baseline yet")
        self.assertEqual(
            pd.BASELINE.read_bytes(), dump_json(pd.build_report()),
            "metrics/proposal-baseline.json is stale. Regenerate with "
            "./scripts/propose_descriptions.py")

    def test_scoring_calls_no_model(self):
        """The reason --check is free. Asserted, not assumed."""
        source = (REPO_ROOT / "scripts" / "propose_descriptions.py").read_text(
            encoding="utf-8")
        for smell in ("anthropic", "openai", "requests.post", "urllib.request"):
            self.assertNotIn(smell, source.lower(),
                             f"{smell} in a script CI runs for free")


if __name__ == "__main__":
    unittest.main()
