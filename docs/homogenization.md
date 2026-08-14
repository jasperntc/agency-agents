# Case study: the Fable upgrade

The founding evidence for this project. A plausible, well-intentioned,
validation-passing mass upgrade made the library measurably worse along a
dimension nothing was watching.

## What happened

Branch `archive/fable-upgrade` (merge-base `459dce8`) is an autonomous AI
upgrade run against the agent library. Its own log describes the intent:

> Autonomous upgrade per Upgrade Rigor Framework: THOUGHT_TRACE scaffolding,
> niche expertise density, expanded negative constraints, production-grade
> deliverables.

It modified **263 of 264** agent files in a single commit, adding 4,521 lines
and removing 1,445.

**Every existing check passed.** Frontmatter was valid. Required fields were
present. Division consistency held. Runbook slugs resolved. The originality
check found no duplicates. There was nothing to fail.

## What the existing checks could not see

`scripts/check-agent-originality.sh` flags an agent whose **maximum** pairwise
similarity to any other agent crosses WARN 20% / FAIL 40%. Across the upgrade:

```
max pairwise similarity:  4.7377%  ->  4.7490%     (+0.0113 percentage points)
```

Nowhere near either threshold, before or after. The check is well built and
correctly calibrated — it simply answers a different question. *"Is any one
agent a near-copy of another?"* stayed **no**. Meanwhile:

| metric | before | after | change |
| --- | ---: | ---: | ---: |
| median pairwise similarity | 0.0000% | 0.1381% | 0 → nonzero |
| p95 pairwise similarity | 0.0000% | 0.3954% | 0 → nonzero |
| p99 pairwise similarity | 0.0661% | 0.6208% | +839% |
| mean-of-max per file | 0.2132% | 0.6735% | +216% |
| headers in ≥50% of files | 9 | 11 | +22% |
| headers in ≥75% of files | 1 | 4 | +300% |
| total corpus words | 459,560 | 520,223 | +13.2% |
| mean words per agent | 1,747 | 1,978 | +13.2% |
| shared blocks (≥3 files) | 11 | 92 | +736% |
| duplicated word % | 0.0629% | 0.9702% | **+1442%** |

Two headers spread across the library: `analytical discipline` reached 89% of
files, `negative constraints never violate` reached 78%.

Reproduce it:

```bash
./scripts/corpus_diversity.py --compare 459dce8 archive/fable-upgrade
```

## The lesson

**A maximum cannot detect a distribution shift.** Every pair got slightly more
alike. No pair became a duplicate. Any check that reduces the corpus to its
worst pair is structurally blind to this, no matter how it is tuned.

**Verbatim shared text is the sharpest signal.** `duplicated_word_pct` moved
~15× more than any similarity percentile. A template fragment sprinkled across
200 files barely shifts pairwise similarity — each pair still shares only a
little — but it shows up immediately as duplicated words. If only one metric
could be kept, it would be this one.

**Growth is not improvement.** The corpus gained 60,663 words. Nothing in that
number says whether any agent got better at its job. Answering that requires
behavioural evaluation (Phases 6–7), which is why size is tracked as a *cost* to
be justified rather than an achievement.

**Structural validation cannot answer quality questions.** Everything the
repository could check was green. That is the gap this project exists to close.

## How it is used now

`archive/fable-upgrade` is a **labeled known-bad corpus** — a real regression
with a known cause, permanently available for testing detectors against.
`tests/test_corpus_diversity.py` asserts:

1. the clean baseline passes the gate;
2. the Fable corpus fails it;
3. it fails on ≥3 dimensions including ≥1 distribution metric — breadth, so a
   single tripped threshold cannot be mistaken for a regression;
4. **negative control**: max pairwise similarity stays below the legacy WARN
   threshold on *both* corpora and moves <0.5pp, documenting in an executable
   assertion why the legacy check is insufficient;
5. every threshold sits strictly between the measured baseline and the measured
   Fable value;
6. the observations recorded in `metrics/thresholds.json` match what the tool
   measures today.

Assertions 5 and 6 make the governance rule mechanical. Raising a limit past the
known-bad value fails (5); lowering it past the baseline fails (1); editing the
recorded provenance to justify either fails (6). **A threshold cannot be quietly
loosened to make a failing change pass.** Both were verified by mutation:
loosening `duplicated_word_pct` to 1.5 and falsifying the recorded Fable median
each produce a specific, named failure.

Running `--gate` against Fable prints the whole point in one screen: nine
`BREACH` rows, and `pairwise.max_pct` marked `ctrl`, passing.

## Do not delete this branch

`archive/fable-upgrade` and merge-base `459dce8` are test fixtures now. They are
the only real regression this project owns, and every future detector should be
tried against them before being trusted.
