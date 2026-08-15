# Routing evaluation

**Does the Agency pick the right specialist?** The router skill turns a task into
a grep against an index of 270 descriptions, then loads one agent. Phase 6
measures how well that works, and — just as importantly — states plainly which
half of it a deterministic harness cannot judge at all.

```bash
./scripts/eval_routing.py                # measure and refresh the baseline
./scripts/eval_routing.py --check        # CI: fail if the baseline is stale
./scripts/eval_routing.py --gate         # CI: fail on a threshold breach
./scripts/eval_routing.py --explain c041 # every query tried for one case
./scripts/eval_routing.py --ref <ref>    # measure any git ref
```

## What is and is not measured

Routing has two steps. A model picks search terms; grep does the rest. Only the
second is deterministic, so only the second is measured here.

| step | measured | why |
| --- | --- | --- |
| Is the right agent **findable** from the task's words? | yes | pure text, free, runs on every PR |
| Does the model **choose well** among what it found? | no | needs a model in the loop, and therefore a CI budget (**D5**, still open) |

This is a floor, not a ceiling. A model can translate "second pair of eyes on
this pull request" into `code review` before grepping; the harness cannot. So a
case counted as unreachable does not mean routing fails — it means routing there
depends entirely on the model's vocabulary, and the harness names exactly which
cases those are.

## The benchmark

`eval/routing/cases.jsonl` — 58 tasks written in the vocabulary a *user* would
use, each with the specialist that should be found. Some accept more than one
answer where two agents genuinely overlap.

The obvious way to build this benchmark is also worthless: generate task text
from each agent's description and you have measured whether text matches itself,
scored ~100%, and learned nothing. Two mechanical guards exist because that trap
is easy to fall into gradually rather than all at once.

- **Leakage.** Every case's token overlap with its expected agent's description
  is computed and reported. Median **0.0271**, worst **0.125**. The gate fails
  above 0.10 median / 0.35 worst.
- **Negative control.** Every case is re-scored against the *wrong* agent
  (expectations rotated by one). If that scores nearly as well as the real
  pairing, a "hit" means nothing.

`cases.total` is also ratcheted: the benchmark may grow but never shrink, because
deleting the cases that fail is the cheapest way to make every other number here
improve.

## Results

Measured on 270 agents, 58 cases:

| query strategy | hit % | control % | **lift** | median noise | max noise |
| --- | ---: | ---: | ---: | ---: | ---: |
| every word OR'd | 67.24 | 8.62 | **58.62** | 29.5 | 127 |
| the user's own phrases | 6.90 | 0.00 | 6.90 | 1 | 2 |
| every word stemmed, OR'd | 74.14 | 18.97 | 55.17 | 44.5 | 214 |
| narrowest query (oracle) | 67.24 | 8.62 | **58.62** | 3 | 50 |

**Lift** — hit rate minus that same query's score against the wrong agent — is
the only column comparable between rows. Widening a query raises the hit rate for
free and raises the control with it.

Three findings.

**1. A third of tasks share no word with the right specialist.** Literal
reachability is 67.24%. The other 19 cases are named in the baseline under
`literal_reachability.requires_expansion`. They fail for ordinary reasons: the
code reviewer's description never says "pull request", the SRE's never says
"downtime", the recruiter's never says "applicants". Routing those depends on
the model knowing that a practitioner calls it *code review*, *error budget*,
*talent acquisition*. That is now the router skill's first instruction, with
these numbers as the justification.

**2. A narrow query costs nothing and removes almost all the noise.** Recall for
the word bag and for the narrowest query is *identical* — necessarily so, since a
phrase can only match a line whose text contains its first word. They differ only
in what comes back: a median of 3 agents versus 29.5, worst case 50 versus 127.
Half the corpus, for the same answer.

**3. Stemming looks like an improvement and is not.** Stemming every word lifts
the hit rate from 67.24% to 74.14% — and lifts the wrong-agent rate from 8.62% to
18.97%. The gain in lift is *negative*: 55.17 against 58.62. Four cases are
genuinely recovered by stemming, and more than four are newly matched to the
wrong specialist. Without the control this would have read as a 7-point
improvement and gone straight into the guidance.

## The known-bad corpus does not move these numbers at all

`archive/fable-upgrade` is this repository's labeled failure: an autonomous mass
upgrade that rewrote 263 of 264 agents while every check of the day passed. It
moves nine corpus-diversity dimensions by up to +1442%.

It moves every routing metric by **exactly zero**:

| ref | literal reachability | bag lift | wrong-agent rate |
| --- | ---: | ---: | ---: |
| clean HEAD | 67.24% | 58.62 | 8.62% |
| `459dce8` (the upgrade's merge base) | 65.52% | 58.62 | 6.90% |
| `archive/fable-upgrade` (known bad) | 65.52% | 58.62 | 6.90% |

The known-bad ref and its own merge base are identical on every metric. The
reason is not subtle once seen: routing reads frontmatter `description` fields,
and the upgrade rewrote agent *bodies*.

This is the same lesson as `pairwise.max_pct` in
[homogenization.md](homogenization.md), arriving from the other direction.
Maximum pairwise similarity is blind to homogenization; routing metrics are blind
to it too; and corpus-diversity metrics are in turn blind to descriptions
converging into interchangeable marketing copy. **A passing routing gate is not
evidence the corpus is healthy, and a passing diversity gate is not evidence
routing works.** It is also the concrete reason this project reports every metric
individually and refuses an aggregate score — an average of these two instruments
would have hidden the Fable regression just as effectively as the checks that
actually did.

Recorded in `metrics/routing-thresholds.json` under
`known_bad_does_not_separate`, and pinned by
`test_known_bad_corpus_does_not_move_routing` so a later change to what the
harness reads cannot quietly overturn it.

### So the detector is proved another way

A metric that does not move on the only labeled bad corpus available is
indistinguishable from a metric that cannot move. `eval/routing` therefore
carries a **positive control**: replace all 270 descriptions with one generic
blurb — *"Expert specialist providing comprehensive strategic guidance and best
practice recommendations for your project needs"* — and re-measure.

| | lift | literal reachability |
| --- | ---: | ---: |
| real descriptions | 58.62 | 67.24% |
| all descriptions flattened | 12.07 | 20.69% |

Lift collapses by 79% and lands below the gate's floor of 45.0. The residual
signal is agent *names*, which the flattening leaves alone — worth knowing:
roughly a fifth of routing works off names.

`test_homogenized_descriptions_collapse_lift` asserts both the collapse and that
a fully homogenized index would fail the gate rather than squeak past.

## What CI enforces

| check | mode |
| --- | --- |
| `eval_routing.py --check` — the committed baseline is current | **hard** |
| `tests/test_eval_routing.py` — 12 tests incl. both controls | **hard** |
| `eval_routing.py --gate` — thresholds | advisory until **2026-10-15** |

The gate is advisory for the same reason the corpus-diversity gate was: its
thresholds sit around a single clean observation, with no known-bad corpus to
bracket them from the other side. Promote it once it has run on 20 merged PRs
with no false positive. Unlike the diversity thresholds, these make **no**
strictly-between calibration claim, and `metrics/routing-thresholds.json` says so
in the file rather than leaving the omission to be noticed.

An expectation naming an agent that does not exist is not a threshold breach but
an immediate failure — it means a rename slipped through and every score computed
against it is wrong rather than merely low.

## Adding cases

Add a line to `eval/routing/cases.jsonl`:

```json
{"case": "c059", "kind": "independent", "task": "...", "expect": ["agent-id"], "why": "..."}
```

Then run `./scripts/eval_routing.py` and commit the refreshed baseline, and raise
`cases.total` in `metrics/routing-thresholds.json`.

Three rules, all of which exist to stop the benchmark flattering itself:

1. **Write the task first, in the user's words.** Do not open the agent file and
   paraphrase its description. If you must check which agent you mean, write the
   task before you look.
2. **A case that fails is a result, not a bug.** The 19 unreachable cases are the
   most useful part of this benchmark. Do not reword a task until it passes.
3. **Never lower `cases.total`.** If a case is genuinely wrong — the expected
   agent was mislabeled — fix the expectation rather than deleting the case.

`kind` is `independent`, `paraphrase`, or `adversarial`. Mark a case
`adversarial` when its surface vocabulary points at the wrong specialist; those
are the ones worth having.

## Open

- **D5 (CI budget)** gates model-in-the-loop evaluation: whether the model
  *chooses* well among reachable candidates. Everything here measures whether it
  *can* find them.
- 58 cases across 17 divisions is thin — `specialized` alone holds 57 agents.
  Coverage is unbalanced by design for now (breadth over depth), and the ratchet
  means it can only improve.
