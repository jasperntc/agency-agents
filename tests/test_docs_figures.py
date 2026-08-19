#!/usr/bin/env python3
"""Every figure a doc presents as measured must still be the measured value.

WHY THIS EXISTS

docs/consuming.md quoted 67% literal reachability for a week after the real
figure became 65.52%. The guard meant to prevent exactly that --
test_skill_guidance_quotes_the_live_measurement -- was correct, and was pointed
at SKILL.md alone, while the claim it protects lives in several files. Sweeping
the rest then found three more: docs/metrics.md and docs/corpus-metrics.md both
described their baseline as the fork-point tag when both had been deliberately
re-baselined, and two figures had drifted with them.

Prose that cites evidence is worse than prose that does not, once the evidence
has moved. It reads as verified.

DESIGN

The claims are a table, not a pile of assertions, so what is covered is legible
at a glance and adding a claim is one line. Each entry is
(doc, quoted-substring, source) where source is a callable returning the value
that substring must contain.

Deliberately literal: it asserts the exact string a reader sees, including
thousands separators. A test that compared parsed numbers would pass while the
page rendered `473,579`.

WHAT THIS CANNOT COVER, and it is worth naming: a figure no committed artifact
holds. `docs/corpus-metrics.md` claims 106 of 270 agents have zero max
similarity, and the harness reports percentiles rather than that count. That
claim is marked in the doc as not machine-verified rather than left to look like
the others.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def text(rel: str) -> str:
    """Doc text with whitespace collapsed -- prose is hard-wrapped at 80."""
    return " ".join((REPO_ROOT / rel).read_text(encoding="utf-8").split())


# (doc, substring that must appear, how to derive it)
CLAIMS: list[tuple[str, str, callable]] = [
    # --- docs/metrics.md, from metrics/inventory-baseline.json ---
    ("docs/metrics.md", "Total body words | 502,634",
     lambda: f"Total body words | "
             f"{load('metrics/inventory-baseline.json')['summary']['total_body_words']:,}"),
    ("docs/metrics.md", "| Agents | 270 |",
     lambda: f"| Agents | "
             f"{load('metrics/inventory-baseline.json')['summary']['total_agents']} |"),
    ("docs/metrics.md", "Stem ≠ name-slug | 198",
     lambda: f"Stem ≠ name-slug | "
             f"{load('metrics/inventory-baseline.json')['summary']['stem_slug_mismatches']}"),

    # --- docs/corpus-metrics.md, from metrics/diversity-baseline.json ---
    ("docs/corpus-metrics.md", "| distinct headers | 4,909 |",
     lambda: f"| distinct headers | "
             f"{load('metrics/diversity-baseline.json')['vocabulary']['distinct_headers']:,} |"),
    ("docs/corpus-metrics.md", "| total words | 473,566 |",
     lambda: f"| total words | "
             f"{load('metrics/diversity-baseline.json')['size']['total_words']:,} |"),
    ("docs/corpus-metrics.md", "| max pairwise | 4.7377% |",
     lambda: f"| max pairwise | "
             f"{load('metrics/diversity-baseline.json')['pairwise']['max_pct']}% |"),
    ("docs/corpus-metrics.md", "| mean-of-max per file | 0.2074% |",
     lambda: f"| mean-of-max per file | "
             f"{load('metrics/diversity-baseline.json')['pairwise']['mean_of_max_per_file_pct']}% |"),
    ("docs/corpus-metrics.md", "| shared blocks (≥3 files) | 11 |",
     lambda: f"| shared blocks (≥3 files) | "
             f"{load('metrics/diversity-baseline.json')['boilerplate']['shared_blocks']} |"),

    # --- docs/promotion.md, from metrics/promotion-thresholds.json ---
    ("docs/promotion.md", "**21** of 263",
     lambda: f"**{load('metrics/promotion-thresholds.json')['calibration']['agents_caught_at_current_thresholds']['max_similarity_delta_over_1.0']}**"
             f" of {load('metrics/promotion-thresholds.json')['calibration']['agents_caught_at_current_thresholds']['of_total']}"),
    ("docs/promotion.md", "**32** of 263",
     lambda: f"**{load('metrics/promotion-thresholds.json')['calibration']['agents_caught_at_current_thresholds']['duplicated_word_delta_over_2.0']}**"
             f" of {load('metrics/promotion-thresholds.json')['calibration']['agents_caught_at_current_thresholds']['of_total']}"),

    # --- docs/conversion-determinism.md, from metrics/conversion-manifest.json ---
    ("docs/conversion-determinism.md", "4,055",
     lambda: f"{load('metrics/conversion-manifest.json')['summary']['files']:,}"),

    # --- docs/findings.md + README.md, from the three eval baselines ---
    # findings.md is the summary a reader reaches first and the one most likely
    # to be quoted onward, so every figure in it is bound to its artifact here.
    # The README carries the same headline for the same reason.
    ("docs/findings.md", "literal reachability: 65.52%",
     lambda: f"literal reachability: "
             f"{load('metrics/selection-baseline.json')['literal_reachability_pct']}%"),
    ("docs/findings.md", "58 blind cases, one model, no access to the answer. "
                         "**100% accuracy.**",
     lambda: f"{load('metrics/selection-baseline.json')['cases']['total']} blind "
             f"cases, one model, no access to the answer. "
             f"**{load('metrics/selection-baseline.json')['runs'][0]['accuracy_pct']:g}% "
             f"accuracy.**"),
    ("README.md", "**yes** — 100% on 58 blind cases",
     lambda: f"**yes** — "
             f"{load('metrics/selection-baseline.json')['runs'][0]['accuracy_pct']:g}% on "
             f"{load('metrics/selection-baseline.json')['cases']['total']} blind cases"),
    ("docs/findings.md", "**18 blind subagents, 6 tasks, 144 executed acceptance checks.**",
     lambda: f"**18 blind subagents, "
             f"{load('metrics/construction-baseline.json')['tasks']['total']} tasks, "
             f"{sum(c['checks_total'] for c in load('metrics/construction-baseline.json')['runs'][0]['conditions'].values())}"
             f" executed acceptance checks.**"),
]


class DocFigures(unittest.TestCase):
    def test_every_claimed_figure_is_the_derived_one(self):
        for doc, quoted, derive in CLAIMS:
            with self.subTest(doc=doc, quoted=quoted):
                self.assertEqual(
                    quoted, derive(),
                    f"{doc}: the table entry no longer matches its source "
                    f"artifact. Re-derive the figure and update the doc.")
                self.assertIn(
                    quoted, text(doc),
                    f"{doc} no longer contains {quoted!r}. Either the figure "
                    f"drifted or the prose was reworded -- update CLAIMS in "
                    f"tests/test_docs_figures.py so coverage is not silently lost.")

    def test_baseline_provenance_is_described_correctly(self):
        """The defect that started this: docs claiming the wrong ref.

        Both baselines were deliberately re-generated -- inventory tracks the
        working tree so `--check` can pass at all, diversity sits at the end of
        the Step 0.4 repairs -- while both docs still called them the fork-point
        tag. A wrong provenance claim is worse than a wrong number: it makes
        every figure under it unfalsifiable.
        """
        inv_ref = load("metrics/inventory-baseline.json")["ref"]
        self.assertEqual(inv_ref, "WORKING_TREE")
        self.assertIn("working-tree snapshot", text("docs/metrics.md"))
        self.assertNotIn("taken at tag `upstream-baseline-2026-08-13`",
                         text("docs/metrics.md"))

        div_ref = load("metrics/diversity-baseline.json")["ref"]
        self.assertIn(div_ref, text("docs/corpus-metrics.md"),
                      f"docs/corpus-metrics.md does not name the ref its "
                      f"baseline was actually taken at ({div_ref})")

    def test_unverifiable_claims_are_labelled(self):
        """A figure no artifact holds must say so, or it borrows false authority."""
        doc = text("docs/corpus-metrics.md")
        if "106 of 270 agents have a max similarity of exactly zero" in doc:
            self.assertIn("Not machine-verified", doc,
                          "The zero-similarity count has no committed source "
                          "and must stay explicitly labelled as unverified.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
