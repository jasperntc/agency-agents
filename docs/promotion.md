# Promotion

**A change may not degrade the agents it touches, and may not loosen the gate
that would have caught it.** That is the whole policy. This document is the
resolution of decision **D6**.

```bash
./scripts/check_promotion.py --base main
./scripts/check_promotion.py --base main --json
```

## Why a diff gate exists at all

Every other measurement in this repository is corpus-level, and that is correct
for what it was built against: `archive/fable-upgrade` touched 263 files at once
and moved corpus medians hard enough to see.

It is the wrong shape for the ordinary case. A pull request that edits three
agents cannot move a median over 270. Every corpus gate passes, whatever those
three edits did. The same regression, delivered fifty files at a time over six
months, is invisible to all of them.

So this gate ignores the corpus and asks one question per changed file: **is this
agent worse than it was?**

## What fails, and what only gets reported

It does not try to decide whether an edit made an agent *better*. Nothing
mechanical can, and a gate that pretended to would be worse than none — people
would believe it.

It fails on the narrow set of changes that are degradation under any reading.

| rule | limit | why it is not arguable |
| --- | --- | --- |
| `agent.max_similarity_delta` | +1.0 pt | Two specialists converging is a loss of specialization by definition. No edit improves an agent by making it more like a different one. |
| `agent.duplicated_word_delta` | +2.0 pt | Text arriving that already exists verbatim elsewhere. This is how the Fable regression happened, one file at a time. |
| `agent.duplicated_word_pct` | 8.0% | Absolute ceiling. Its real job is *new* files, which have no previous self to be compared against. |
| `agent.max_similarity_pct` | 20.0% | Backstop against a near-duplicate being added. See the note below — it is a negative control. |
| `agent.word_growth_pct` | +50% | **Advisory. Never fails.** |

Growth is reported and never blocks. A rewritten agent legitimately gets longer,
there is no honest way to separate substance from padding by counting words, and
sustained corpus-wide bloat is already covered by `size.mean_words`.

`agent.max_similarity_pct` is retained deliberately as a **negative control**. It
is the same maximum-of-a-distribution statistic that
`scripts/check-agent-originality.sh` gates on, and it moved 0.0113 points across
the Fable upgrade. It stays visible in `metrics/promotion-thresholds.json` so
anyone reading that file sees a threshold that cannot do the job the deltas do.

## Calibration, from both directions

A detector nobody has seen fire is a hypothesis. This one is measured against a
real regression *and* against real ordinary work.

**It fires on the known regression.** Replaying `459dce8 → archive/fable-upgrade`
— 263 agents in common — through these rules:

| | agents caught |
| --- | ---: |
| `max_similarity_delta` > +1.0 | **21** of 263 |
| `duplicated_word_delta` > +2.0 | **32** of 263 |
| `max_similarity_pct` > 20.0 (the absolute bound) | **0** of 263 |

Every failure comes from a delta. The absolute ceiling — the statistic the
repository already had — sees none of it.

**It is silent on ordinary work.** Five real changes from this repository's
history, 11 agents added and 65 modified, all pass with zero failures:

| commit | change |
| --- | --- |
| `9f3e401` | normalize section headers across 15 agents |
| `86a6695` | add 6 specialists |
| `e4a0fbc` | add a missing trailing newline to 48 agents |
| `c89557f` | add Economy Designer, improve Reality Checker |
| `8ef4923` | add 4 gated single agents |

The header-normalization commit is the hardest of these on purpose: rewriting
section headings toward a common form is exactly the shape of edit that makes
agents look alike. It still passes.

Both directions are pinned in `tests/test_check_promotion.py`, so the thresholds
cannot be loosened on the strength of a false positive that was never there.

Because it is calibrated from both sides, this gate is **hard from day one** —
unlike the diversity and routing gates, which were advisory first.

### One honest limitation

`duplicated_word_pct` is computed against a corpus-wide set of shared blocks, so
an agent's score can move because *other* agents changed. That is real — text
becomes boilerplate when someone else copies it — but it means a delta here is
not always caused by the edit to that file. In practice it only bites when a
single change touches both an agent and something that shares text with it,
which is a case worth looking at anyway.

## The ratchet (D6)

Every threshold in `metrics/*thresholds.json` **may be tightened freely and may
not be loosened**. A raised `max`, a lowered `min`, or a deleted entry all fail
the build.

Without this, every gate in the repository is advisory in practice. The cheapest
way to land a change that trips a threshold is to edit the threshold in the same
commit, and in a large diff nobody notices.

**There is an escape hatch, and it is deliberate.** A ratchet with no release
gets bypassed by deleting the check instead, which is strictly worse. Add a
`loosened_why` to the entry:

```json
"size.mean_words": {
  "max": 2100,
  "loosened_why": "corpus grew from 270 to 480 agents; re-measured on the new set"
}
```

The build passes and the reason sits in the diff where a reviewer reads it. A
`loosened_why` already present in the base does **not** excuse a further move —
otherwise one sentence written once would license every future loosening of that
threshold forever.

Adding a new gate means adding its file to `RATCHETED` in
`scripts/check_promotion.py`. `test_every_thresholds_file_is_ratcheted` fails if
you forget, because forgetting is otherwise silent: the gate works, and its
thresholds can be edited downward at will.

## What this does not cover

Stated plainly, in the manner of [SECURITY.md](../SECURITY.md):

- **Whether an edit is an improvement.** Only whether it is one of a few
  specific kinds of degradation.
- **Behaviour.** These are lexical measurements. An agent rewritten into
  confident, well-differentiated, wrong advice passes everything here.
- **Removals.** Deleting an agent is reported and never blocked; that is a
  product decision, not a quality regression.
- **Non-agent files.** Scripts, docs and schemas are covered by their own
  checks, not by this one.

## Where it runs

`pull_request` only. There is no meaningful "what did this change" question once
a squash merge has landed — the comparison belongs at the point where its answer
can still alter the outcome.

The base is the **merge base**, not the tip of the base branch, so work that
landed on `main` after branching is not attributed to this change.
`check-identity.py` resolves its base the same way, deliberately.
