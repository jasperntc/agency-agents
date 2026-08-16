#!/usr/bin/env python3
"""Regression tests for the routing evaluation gate.

    python3 tests/test_eval_routing.py

Two of these matter more than the rest.

test_homogenized_descriptions_collapse_lift is a POSITIVE control. The known-bad
corpus this repository owns -- archive/fable-upgrade -- moves every routing
metric by exactly zero, because it rewrote agent bodies and routing reads
frontmatter descriptions. Without a positive control, a metric that never moves
on the one labeled bad corpus available is indistinguishable from a metric that
cannot move at all. So the failure it targets is constructed directly and the
gate is shown to fire on it.

test_known_bad_corpus_does_not_move_routing pins that null result in place. It
is not decoration: if someone later "improves" this harness by feeding it agent
bodies, these numbers would start moving and the test would fail, forcing an
explicit decision rather than a silent change of what is being measured.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_routing as er  # noqa: E402

KNOWN_BAD_REF = "archive/fable-upgrade"
KNOWN_BAD_MERGE_BASE = "459dce8"
THRESHOLDS = REPO_ROOT / "metrics" / "routing-thresholds.json"
BASELINE = REPO_ROOT / "metrics" / "routing-baseline.json"


def thresholds() -> dict:
    return json.loads(THRESHOLDS.read_bytes().decode("utf-8"))


def value(report: dict, path: str):
    node = report
    for part in path.split("."):
        node = node[part]
    return node


class RoutingGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = er.build_report()
        cls.entries = er.load_index()
        cls.cases = er.load_cases()

    # --- the gate does what it says -------------------------------------------

    def test_clean_corpus_passes_every_threshold(self):
        self.assertEqual(er.gate(self.report), [])

    def test_committed_baseline_is_current(self):
        from lib.corpus import dump_json
        self.assertEqual(
            BASELINE.read_bytes(), dump_json(self.report),
            "metrics/routing-baseline.json is stale. Run ./scripts/eval_routing.py",
        )

    def test_recorded_observations_match_reality(self):
        """Every `observed` in the thresholds file is what the code produces.

        A rationale citing a number nobody re-measures is how a threshold file
        drifts into fiction while still looking rigorous.
        """
        for path, rule in thresholds()["thresholds"].items():
            if "observed" not in rule:
                continue
            self.assertEqual(
                rule["observed"], value(self.report, path),
                f"{path}: recorded observation {rule['observed']} is not what "
                f"eval_routing.py measures today",
            )

    def test_thresholds_leave_the_observation_passing(self):
        """No threshold may be set on the wrong side of its own observation."""
        for path, rule in thresholds()["thresholds"].items():
            observed = rule.get("observed")
            if observed is None:
                continue
            if "min" in rule:
                self.assertGreaterEqual(observed, rule["min"], f"{path} min")
            if "max" in rule:
                self.assertLessEqual(observed, rule["max"], f"{path} max")

    # --- the benchmark is not testing text against itself ---------------------

    def test_every_expected_agent_exists(self):
        self.assertEqual(self.report["cases"]["unknown_expected_ids"], [])

    def test_case_ids_are_unique(self):
        ids = [c["case"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_case_is_written_in_the_agents_own_words(self):
        """The tautology guard. A case copied from the description it is meant
        to find scores perfectly and demonstrates nothing."""
        worst = max(self.report["per_case"], key=lambda r: r["description_overlap"])
        self.assertLessEqual(
            worst["description_overlap"], 0.35,
            f"{worst['case']} shares too much vocabulary with its expected agent",
        )

    def test_negative_control_stays_near_zero(self):
        """Scored against the WRONG agent, every strategy must collapse.

        If a query matches so much of the index that it hits the wrong agent
        almost as often as the right one, a 'hit' carries no information and
        every other number in the report is noise.
        """
        nc = self.report["negative_control"]
        self.assertLess(nc["bag_hit_pct"], 20.0)
        self.assertLess(nc["verbatim_phrase_hit_pct"], 10.0)

    # --- the metric can actually detect what it claims to detect --------------

    def test_homogenized_descriptions_collapse_lift(self):
        """POSITIVE CONTROL: make every description identical, lose the signal.

        This is the failure the gate exists to catch -- 270 agents whose
        descriptions have converged on the same confident, generic phrasing, so
        no query can tell them apart. It is constructed rather than sampled
        because the one labeled known-bad corpus available does not exhibit it
        (see test_known_bad_corpus_does_not_move_routing).
        """
        generic = ("Expert specialist providing comprehensive strategic guidance "
                   "and best practice recommendations for your project needs")
        flattened = [
            {**e, "description": generic,
             "line": f"{e['id']} | {e['division']} | {e['name']} | {generic}"}
            for e in self.entries
        ]
        rows = er.evaluate(self.cases, flattened)
        order = [c["expect"] for c in self.cases]
        rotated = {c["case"]: order[(i + 1) % len(order)]
                   for i, c in enumerate(self.cases)}
        control = er.evaluate(self.cases, flattened,
                              expect_of=lambda c: rotated[c["case"]])
        lift = er.with_lift(rows, control, "bag_hit", "bag_matches")["lift_over_control"]

        healthy = self.report["strategies"]["bag"]["lift_over_control"]
        self.assertLess(
            lift, healthy / 2,
            f"Flattening every description left lift at {lift} against a healthy "
            f"{healthy}. The metric is not sensitive to the failure it exists for.",
        )
        self.assertLess(lift, thresholds()["thresholds"]
                        ["strategies.bag.lift_over_control"]["min"],
                        "A fully homogenized index must fail the gate, not squeak past")

    def test_known_bad_corpus_does_not_move_routing(self):
        """Pins the null result, so a later change cannot quietly overturn it.

        archive/fable-upgrade rewrote 263 of 264 agent BODIES. Routing reads
        frontmatter descriptions, so it is blind to that -- the known-bad ref
        and its own merge base score identically on every metric. That is a real
        property of what this instrument measures, recorded in
        metrics/routing-thresholds.json, and it is the reason the routing
        thresholds make no strictly-between calibration claim.
        """
        bad = er.build_report(KNOWN_BAD_REF)
        base = er.build_report(KNOWN_BAD_MERGE_BASE)
        for path in ("literal_reachability.pct",
                     "strategies.bag.lift_over_control",
                     "strategies.bag.hit_pct",
                     "negative_control.bag_hit_pct"):
            self.assertEqual(
                value(bad, path), value(base, path),
                f"{path} now differs between the known-bad corpus and its merge "
                f"base. Either the harness changed what it reads, or the recorded "
                f"finding in metrics/routing-thresholds.json is out of date.",
            )

        recorded = thresholds()["known_bad_does_not_separate"]["measured"]
        self.assertEqual(recorded["archive_fable_upgrade"]["bag_lift"],
                         value(bad, "strategies.bag.lift_over_control"))
        self.assertEqual(recorded["merge_base_459dce8"]["literal_reachability_pct"],
                         value(base, "literal_reachability.pct"))

    # --- the shipped advice still matches the evidence for it -----------------

    def test_skill_guidance_quotes_the_live_measurement(self):
        """The router skill argues from numbers. They must be current numbers.

        The guidance tells a model to translate the task before grepping, and
        justifies it with measured figures. Advice that cites evidence is worse
        than advice that does not once the evidence has moved on, because it
        reads as verified when it is not.
        """
        raw = (REPO_ROOT / "plugins" / "router" / "skills" / "agency-router"
               / "SKILL.md").read_bytes().decode("utf-8")
        # Collapse whitespace: the prose is hard-wrapped at 80 columns, so a
        # quoted figure can land either side of a line break. The test is about
        # the number being current, not about where the paragraph happens to fold.
        skill = " ".join(raw.split())
        quoted = {
            f"{round(self.report['literal_reachability']['pct'])}% of tasks":
                "literal reachability",
            f"{self.report['cases']['total']}-task benchmark": "benchmark size",
            f"median of **{round(self.report['strategies']['bag']['median_matches'])} agents**":
                "noise from OR-ing every word",
            f"as many as {self.report['strategies']['bag']['max_matches']}":
                "worst-case noise",
            f"median of **{round(self.report['strategies']['narrowest_oracle']['median_matches'])}**":
                "noise from a narrow query",
        }
        for phrase, what in quoted.items():
            self.assertIn(
                phrase, skill,
                f"SKILL.md no longer quotes the measured {what}. Update the "
                f"ROUTER_SKILL text in scripts/build_plugins.py and regenerate.",
            )

    def test_consumer_docs_quote_the_live_measurement(self):
        """The same rule for prose a consumer reads before installing anything.

        docs/consuming.md quotes reachability to argue the router is worth its
        context cost. It went stale the moment the benchmark was corrected --
        it said 67% while the skill said 66% -- and nothing caught it, because
        the test above only ever looked at SKILL.md. Found by accident while
        diffing an old branch before deleting it.

        Deliberately loose about WHICH figures appear: a doc may quote a subset
        or none. It is strict that any figure it does quote is the current one,
        which is the only property that matters.
        """
        pct = round(self.report["literal_reachability"]["pct"])
        total = self.report["cases"]["total"]
        for rel in ("docs/consuming.md", "README.md"):
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            text = " ".join(path.read_bytes().decode("utf-8").split())
            if "% of tasks" in text:
                self.assertIn(
                    f"**{pct}% of tasks", text,
                    f"{rel} quotes a stale literal reachability. Current: {pct}%")
            if "-task benchmark" in text:
                self.assertIn(
                    f"{total}-task benchmark", text,
                    f"{rel} quotes a stale benchmark size. Current: {total}")

    # --- determinism ----------------------------------------------------------

    def test_report_is_byte_stable(self):
        from lib.corpus import dump_json
        self.assertEqual(dump_json(er.build_report()), dump_json(er.build_report()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
