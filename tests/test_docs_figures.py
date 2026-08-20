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


def _construction_runs() -> list[dict]:
    """Construction arms, in the order the baseline writes them.

    Index 0 is the Opus arm and index 1 the Sonnet arm, but the claims below
    look the model up by name rather than trusting that order -- an arm added
    or reordered should fail loudly here, not silently rebind a figure to the
    wrong model.
    """
    return load("metrics/construction-baseline.json")["runs"]


def _arm(model: str) -> dict:
    runs = [r for r in _construction_runs() if r["model"] == model]
    assert len(runs) == 1, f"expected exactly one {model} construction arm, got {len(runs)}"
    return runs[0]


def _tasks_answered() -> int:
    """How many tasks the committed arms actually answered.

    Deliberately NOT `baseline['tasks']['total']`, which counts every task
    registered in tasks.jsonl. Registering c007 raised that to 7 while both
    committed arms still answer 6, and binding the sentence to the registry
    would have silently restated the arms as covering a task they never saw.
    """
    counts = {len(c["per_task"])
              for r in _construction_runs() for c in r["conditions"].values()}
    assert len(counts) == 1, f"arms answer differing task counts: {counts}"
    return counts.pop()


def _diag(condition: str) -> dict:
    """The Sonnet diagnosis arm's numbers for one condition."""
    runs = [r for r in load("metrics/behaviour-baseline.json")["runs"]
            if r["model"] == "claude-sonnet-5"]
    assert len(runs) == 1, f"expected one Sonnet diagnosis arm, got {len(runs)}"
    return runs[0]["conditions"][condition]


def _diag_lift(condition: str) -> float:
    runs = [r for r in load("metrics/behaviour-baseline.json")["runs"]
            if r["model"] == "claude-sonnet-5"]
    return runs[0]["lift_over_no_skill"][condition]


def _cell(model: str, condition: str, kind: str) -> str:
    """One `passed/total (pct%)` cell of the construction matrix."""
    k = _arm(model)["conditions"][condition]["by_kind"][kind]
    return f"{k['passed']}/{k['total']} ({k['pass_pct']:g}%)"


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
    ("docs/findings.md", "literal reachability: 70.18%",
     lambda: f"literal reachability: "
             f"{load('metrics/selection-baseline.json')['literal_reachability_pct']}%"),
    ("docs/findings.md", "58 blind cases, one model, no access to the answer. "
                         "**98.28% accuracy.**",
     lambda: f"{load('metrics/selection-baseline.json')['cases']['total']} blind "
             f"cases, one model, no access to the answer. "
             f"**{load('metrics/selection-baseline.json')['runs'][0]['accuracy_pct']:g}% "
             f"accuracy.**"),
    ("README.md", "**yes** — 98.28% on 58 blind cases",
     lambda: f"**yes** — "
             f"{load('metrics/selection-baseline.json')['runs'][0]['accuracy_pct']:g}% on "
             f"{load('metrics/selection-baseline.json')['cases']['total']} blind cases"),
    # --- docs/findings.md, from metrics/construction-baseline.json ---
    # Two arms now. The subagent and check counts are summed across every run
    # so that adding a third arm cannot leave the headline quietly describing
    # only the first two.
    ("docs/findings.md",
     "**36 blind subagents, 6 tasks, two models, 288 executed acceptance checks.**",
     lambda: f"**{sum(len(c['per_task']) for r in _construction_runs() for c in r['conditions'].values())}"
             f" blind subagents, "
             f"{_tasks_answered()} tasks, "
             f"two models, "
             f"{sum(c['checks_total'] for r in _construction_runs() for c in r['conditions'].values())}"
             f" executed acceptance checks.**"),

    # The row that carries the whole Sonnet result: `none` at ceiling on both
    # models is what makes the axis inconclusive rather than null, and the one
    # non-ceiling cell in 36 subagents is the flattened one. Binding the full
    # row keeps the ceiling claim and the exception honest together.
    ("docs/findings.md",
     "| `none` | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) |",
     lambda: f"| `none` | {_cell('claude-opus-5', 'none', 'stated')} | "
             f"{_cell('claude-opus-5', 'none', 'implied')} | "
             f"{_cell('claude-sonnet-5', 'none', 'stated')} | "
             f"{_cell('claude-sonnet-5', 'none', 'implied')} |"),
    # --- docs/findings.md, from metrics/behaviour-baseline.json ---
    # The Sonnet diagnosis arm is the first number in the project to move off
    # zero, so it is the one most likely to be quoted onward and the one that
    # most needs binding to its artifact.
    ("docs/findings.md", "| `none` | **37/40 (92.5%)** | — |",
     lambda: f"| `none` | **{_diag('none')['found']}/{_diag('none')['planted_total']} "
             f"({_diag('none')['recall_pct']:g}%)** | — |"),
    ("docs/findings.md", "| `current` | 35/40 (87.5%) | **-5.0** |",
     lambda: f"| `current` | {_diag('current')['found']}/{_diag('current')['planted_total']} "
             f"({_diag('current')['recall_pct']:g}%) | "
             f"**{_diag_lift('current'):.1f}** |"),

    ("docs/findings.md",
     "| `flattened` | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) | 22/24 (91.67%) |",
     lambda: f"| `flattened` | {_cell('claude-opus-5', 'flattened', 'stated')} | "
             f"{_cell('claude-opus-5', 'flattened', 'implied')} | "
             f"{_cell('claude-sonnet-5', 'flattened', 'stated')} | "
             f"{_cell('claude-sonnet-5', 'flattened', 'implied')} |"),
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
