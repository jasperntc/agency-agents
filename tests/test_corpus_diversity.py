#!/usr/bin/env python3
"""Regression tests for the corpus diversity gate.

The point of these tests is not that the code runs. It is that the gate fires on
a REAL known-bad corpus -- archive/fable-upgrade, an autonomous mass upgrade
that rewrote 263 of 264 agents while every existing check passed.

A detector nobody has seen fire is a hypothesis. This repository happens to own
a labeled positive, so the detector is tested against it rather than against a
synthetic fixture.

    python3 tests/test_corpus_diversity.py

Requires the git refs `upstream-baseline-2026-08-13` and `archive/fable-upgrade`
to exist locally. Nothing is checked out: blobs stream via `git cat-file`.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import corpus_diversity as cd  # noqa: E402

BASELINE_REF = "upstream-baseline-2026-08-13"
KNOWN_BAD_REF = "archive/fable-upgrade"
THRESHOLDS = REPO_ROOT / "metrics" / "thresholds.json"

# The statistic scripts/check-agent-originality.sh gates on.
LEGACY_WARN_PCT = 20.0
LEGACY_FAIL_PCT = 40.0

# Metrics describing the shape of the pairwise similarity distribution, as
# opposed to size or vocabulary. At least one must fire on the known-bad corpus:
# if only "the files got longer" fired, we would be measuring bloat, not
# homogenization.
DISTRIBUTION_METRICS = {
    "pairwise.median_pct",
    "pairwise.p95_pct",
    "pairwise.p99_pct",
    "pairwise.mean_of_max_per_file_pct",
}

_measured: dict[str, dict] = {}
_config: dict = {}


def setUpModule() -> None:
    global _config
    _config = json.loads(THRESHOLDS.read_bytes().decode("utf-8"))
    for ref in (BASELINE_REF, KNOWN_BAD_REF):
        _measured[ref] = cd.measure(ref)


def gate(ref: str) -> list[dict]:
    return cd.evaluate_gate(_measured[ref], _config)


def breaches(ref: str) -> list[dict]:
    return [r for r in gate(ref) if r["breached"]]


class TestGate(unittest.TestCase):
    def test_a_baseline_passes(self):
        """The clean baseline must pass every dimension.

        A gate that fails its own baseline is not a gate, it is noise.
        """
        failed = breaches(BASELINE_REF)
        self.assertEqual(
            failed, [],
            f"baseline {BASELINE_REF} breached: {[r['metric'] for r in failed]}",
        )

    def test_b_known_bad_fails(self):
        """The known-bad corpus must fail."""
        self.assertTrue(
            breaches(KNOWN_BAD_REF),
            f"{KNOWN_BAD_REF} passed the gate -- the detector does not detect the "
            f"one regression we know actually happened",
        )

    def test_c_known_bad_fails_broadly(self):
        """At least 3 dimensions, including at least one distribution metric.

        Breadth matters: a single tripped threshold could be a coincidence or an
        over-tight limit. Nine independent axes moving together is a regression.
        """
        names = {r["metric"] for r in breaches(KNOWN_BAD_REF)}
        self.assertGreaterEqual(
            len(names), 3, f"expected >=3 breached dimensions, got {sorted(names)}"
        )
        self.assertTrue(
            names & DISTRIBUTION_METRICS,
            f"no pairwise-distribution metric fired ({sorted(names)}); the gate may "
            f"be detecting size growth rather than homogenization",
        )

    def test_d_negative_control_max_pairwise_is_blind(self):
        """Max pairwise similarity CANNOT detect this regression.

        This is the whole reason the tool exists. check-agent-originality.sh
        thresholds on maximum pairwise similarity at WARN 20% / FAIL 40%. On both
        corpora that number sits near 4.7%, nowhere near either threshold, and it
        moves by ~0.01 percentage points across an upgrade that homogenized the
        library on nine other axes.

        If this test ever fails, the legacy check has become sufficient on its
        own and this tool's justification needs revisiting.
        """
        base = _measured[BASELINE_REF]["pairwise"]["max_pct"]
        bad = _measured[KNOWN_BAD_REF]["pairwise"]["max_pct"]

        for ref, value in ((BASELINE_REF, base), (KNOWN_BAD_REF, bad)):
            self.assertLess(
                value, LEGACY_WARN_PCT,
                f"{ref} max pairwise {value}% would have tripped the legacy WARN "
                f"threshold ({LEGACY_WARN_PCT}%)",
            )
            self.assertLess(value, LEGACY_FAIL_PCT)

        self.assertLess(
            abs(bad - base), 0.5,
            f"max pairwise moved {abs(bad - base):.4f}pp; the negative control "
            f"assumes it is effectively static ({base}% -> {bad}%)",
        )

    def test_e_thresholds_sit_between_observations(self):
        """Every threshold must be strictly between baseline and known-bad.

        This is what makes 'do not loosen a threshold to make CI pass' an
        enforced rule rather than a comment: raising a limit past the known-bad
        value fails here, and lowering it past the baseline fails test_a.
        """
        for metric, spec in sorted(_config["thresholds"].items()):
            if spec.get("negative_control"):
                continue
            with self.subTest(metric=metric):
                worst_baseline = max(
                    spec["observed_baseline_tag"], spec["observed_baseline_merge_base"]
                )
                self.assertGreaterEqual(
                    spec["max"], worst_baseline,
                    f"{metric}: threshold {spec['max']} is below the measured "
                    f"baseline {worst_baseline} -- the clean corpus cannot pass",
                )
                self.assertLess(
                    spec["max"], spec["observed_known_bad"],
                    f"{metric}: threshold {spec['max']} is at or above the "
                    f"known-bad value {spec['observed_known_bad']} -- this "
                    f"dimension can no longer detect the regression",
                )

    def test_f_recorded_observations_match_reality(self):
        """The values recorded in thresholds.json must match what we measure now.

        Stops the provenance in thresholds.json from drifting into fiction.
        """
        for metric, spec in sorted(_config["thresholds"].items()):
            with self.subTest(metric=metric):
                self.assertAlmostEqual(
                    cd.dig(_measured[BASELINE_REF], metric),
                    spec["observed_baseline_tag"], places=3,
                    msg=f"{metric}: recorded baseline does not match measurement",
                )
                self.assertAlmostEqual(
                    cd.dig(_measured[KNOWN_BAD_REF], metric),
                    spec["observed_known_bad"], places=3,
                    msg=f"{metric}: recorded known-bad value does not match measurement",
                )


class TestDeterminism(unittest.TestCase):
    def test_measurement_is_reproducible(self):
        """Same ref, same bytes. A flapping metric poisons every comparison."""
        again = cd.measure(BASELINE_REF)
        self.assertEqual(
            cd.dump_json(cd.comparable(again)),
            cd.dump_json(cd.comparable(_measured[BASELINE_REF])),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
