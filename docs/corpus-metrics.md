# Corpus diversity metrics

`scripts/corpus_diversity.py` measures homogenization across the **whole** agent
library, as opposed to `scripts/check-agent-originality.sh`, which asks whether
any single agent is too close to another. Both are needed. They answer different
questions and neither substitutes for the other.

## The case that motivates it

Branch `archive/fable-upgrade` is an autonomous mass "upgrade" that rewrote 263
of 264 agents. Every existing check passed. Measured against its merge-base
`459dce8`:

| metric | before | after | change |
| --- | ---: | ---: | ---: |
| **max pairwise similarity** | **4.7377%** | **4.7490%** | **+0.2%** |
| median pairwise | 0.0000% | 0.1381% | 0 → nonzero |
| p95 pairwise | 0.0000% | 0.3954% | 0 → nonzero |
| p99 pairwise | 0.0661% | 0.6208% | +839% |
| mean-of-max per file | 0.2132% | 0.6735% | +216% |
| distinct headers | 4,784 | 4,778 | −0.1% |
| headers in ≥50% of files | 9 | 11 | +22% |
| headers in ≥75% of files | 1 | 4 | +300% |
| total corpus words | 459,560 | 520,223 | +13.2% |
| mean words per agent | 1,747 | 1,978 | +13.2% |
| shared blocks (≥3 files) | 11 | 92 | +736% |
| **duplicated word %** | **0.0629%** | **0.9702%** | **+1442%** |

Two new headers entered the top 20: `analytical discipline` (89% of files) and
`negative constraints never violate` (78%).

The existing originality gate thresholds on **maximum** pairwise similarity
(WARN ≥20%, FAIL ≥40%). That number moved by 0.0113 percentage points. The gate
is not mistuned — it measures a different axis. Homogenization appears in the
distribution, the shared vocabulary, and the volume of verbatim-shared text.

**Verbatim shared text is the sharpest detector**: `duplicated_word_pct` moved
roughly 15× more than any similarity percentile. A template fragment sprinkled
across many files barely moves pairwise similarity — each pair still shares only
a little — but it shows up immediately as duplicated words.

## What is measured

**Pairwise distribution** — median, p95, p99, max Jaccard over 8-word shingles;
mean-of-max per file; counts of pairs ≥5%, ≥10%, ≥20%.

**Header vocabulary** — distinct normalized `##`/`###` headers, and how many are
present in ≥25% / ≥50% / ≥75% of files. A library converging on one template
shows up here before the prose itself looks alike.

**Size** — total, mean, median, p10, p90 words; mean per division. Instruction
bloat is a tracked regression, not a neutral fact.

**Shared boilerplate** — 12-word runs appearing verbatim in ≥3 files, plus the
share of corpus words sitting inside such a run.

**Per agent** — each agent's max similarity and its closest neighbour, so a
corpus-level signal can be drilled into.

## Usage

```bash
# Measure a ref and write the artifact
./scripts/corpus_diversity.py --ref upstream-baseline-2026-08-13 --out metrics/diversity-baseline.json

# Delta between two refs
./scripts/corpus_diversity.py --compare 459dce8 archive/fable-upgrade

# Verify the corpus still matches a recorded baseline
./scripts/corpus_diversity.py --check metrics/diversity-baseline.json
```

Runs in ~2s per ref. `--ref` streams blobs via `git cat-file --batch`, so
`archive/fable-upgrade` is measured without ever checking it out.

## Baseline

`metrics/diversity-baseline.json` at commit `c7f51dd` — the end of the Step 0.4
source repairs, **not** the fork-point tag. It was re-baselined there
deliberately, because Step 0.4 fixed genuine defects (mojibake, truncation) and
measuring diversity against uncorrected text would have carried those defects
into every later comparison. 270 agents:

| metric | value |
| --- | ---: |
| median / p95 / p99 pairwise | 0.0% / 0.0% / 0.0635% |
| max pairwise | 4.7377% |
| mean-of-max per file | 0.2074% |
| distinct headers | 4,909 |
| headers in ≥50% / ≥75% of files | 9 / 1 |
| total words | 473,566 |
| mean words per agent | 1,754 |
| shared blocks (≥3 files) | 11 |
| duplicated word % | 0.0610% |

106 of 270 agents have a max similarity of exactly zero — they share no 8-word
run with any other agent. That is what a healthy, genuinely specialized library
looks like.

> **Not machine-verified.** Every other figure in this table is re-derived from
> `metrics/diversity-baseline.json` by `tests/test_docs_figures.py`. This one and
> the nonzero-only mean below are not: the harness reports distribution
> percentiles, not the per-file zero count, so no committed artifact holds them.
> They were measured once, at the same time and from the same corpus as the rest
> of the table. Treat them as a one-time observation rather than a live metric,
> or add the count to `corpus_diversity.measure()` to make them checkable.

## Design decisions worth keeping

**Tokenization is identical to `check-agent-originality.sh`** — same
entity-neutralization list, same 8-word shingles. Only the *statistic* differs.
If the tokenizers diverge, the two tools disagree about the same corpus and
neither can be trusted. Keep the `ENTITY` regexes in sync.

**No aggregate score.** Every metric is reported separately. A single blended
number is exactly how the Fable regression stayed invisible.

**`mean-of-max` is averaged over all agents, including zeros.** Averaging only
over agents with nonzero similarity inflates the figure (0.3415% vs 0.2074% on
the baseline) and makes it move for the wrong reason — an agent going from 0 to
0.01 would *lower* the nonzero-only mean.

**Ranking never uses `Counter.most_common()`.** It breaks ties by insertion
order, and these counters are fed from set iteration, whose order Python
randomizes per process via `PYTHONHASHSEED`. Sorting its output does not help —
it has already chosen a different tied subset. See `rank()`.

**stdout carries JSON only; all human output goes to stderr.** Otherwise a
redirected run captures the summary table and the artifact is not valid JSON.

## CI status and the promotion policy

`.github/workflows/corpus-metrics.yml` runs on every PR and on push to main.

| step | blocking? | why |
| --- | --- | --- |
| `tests/test_corpus_diversity.py` | **yes** | Tests the detector against fixed refs. Independent of the working tree, so it cannot false-positive on a legitimate change. |
| `--gate metrics/thresholds.json` | **no — advisory until 2026-09-15** | Thresholds are calibrated from a single case study. |
| drift vs frozen baselines | never | Informational only. |

**Why the gate starts advisory.** These thresholds come from exactly one
observed regression. A brand-new gate that blocks on day one will eventually
produce a false positive on a legitimate change, and the first false positive is
what teaches everyone to route around a check. Advisory-first buys the evidence
needed to justify blocking.

**Promotion criteria.** Remove `continue-on-error: true` from the gate step once
it has run on **20 merged changes with zero false positives**. Started
2026-08-14. If a false positive occurs, fix the threshold *with new measured
evidence* (which requires updating `metrics/thresholds.json` and its recorded
observations, which `test_e`/`test_f` will check) and restart the count.

**Why the drift checks never block.** Despite the name, neither baseline is a
fork-point snapshot. `metrics/inventory-baseline.json` records `WORKING_TREE`
and has been re-baselined twice on purpose — after the Step 0.4 repairs, and
again when Phase 3 added `id` to all 270 files. `metrics/diversity-baseline.json`
sits at `c7f51dd`, the end of Step 0.4. So they answer "what has changed since
the last deliberate re-baseline", which is a question, not a verdict. The actual
fork point is tag `upstream-baseline-2026-08-13`, measurable any time with
`--ref`. The `--gate` uses absolute thresholds precisely so it stays
meaningful on any corpus state without a reference artifact.

## Determinism

Verified: five fresh processes and two forced-different `PYTHONHASHSEED` values
all produce byte-identical output, and the stdout path matches the `--out` path
exactly. See `docs/metrics.md` for the shared determinism rules.
