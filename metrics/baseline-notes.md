# Baseline provenance

`metrics/inventory-baseline.json` and `metrics/diversity-baseline.json` record
the accepted state of the corpus. They are regenerated whenever the corpus
changes intentionally, and each move is recorded here.

## Why they move at all

These files answer *"has anything changed since the last accepted state?"*, not
*"what did upstream look like?"* — the second question is always answerable by
re-measuring the immutable tag:

```bash
./scripts/inventory.py --ref upstream-baseline-2026-08-13
./scripts/corpus_diversity.py --ref upstream-baseline-2026-08-13
```

Nothing is lost by re-baselining, so the committed artifacts track the current
accepted state and the fork point stays reproducible on demand.

The CI drift check (`corpus-metrics.yml`) is therefore **informational and never
blocking**. The blocking checks are the diversity `--gate` (absolute thresholds,
meaningful on any corpus state) and the detector's regression test (fixed refs).

---

## Move 1 — 2026-08-14 — `upstream-baseline-2026-08-13` → `c7f51dd`

Step 0.4, source-correctness repairs. **53 of 270 agent files changed** across
six separately revertible commits.

| commit | files | what |
| --- | ---: | --- |
| `71f5589` | 3 | healthcare: folded multi-line frontmatter, removed alignment padding |
| `121969d` | 1 | engineering-developer-tooling-engineer: quoted a description containing `": "` |
| `719747c` | 2 | repaired `0x04` mojibake in section headers — **incomplete, see `c7f51dd`** |
| `e4a0fbc` | 48 | added a missing trailing newline |
| `8cf05ea` | 1 | specialized-workflow-architect: rendered 9 emoji shortcodes |
| `c7f51dd` | 2 | completed the mojibake repair: 21 headers, 1 structural |

`engineering-mobile-app-builder` and `marketing-app-store-optimizer` appear in
three commits each, which is why the file count is 53 rather than the sum.

### A note on `719747c`

That commit fixed 2 of 21 corrupted headers in those two files and reported
success. Its detection regex looked for C0 control characters, which matched
only the pairs whose second byte happened to be `0x04`; the rest use bytes like
`0xE0`, `0xAF`, `0xCB`. The accompanying claim that "the corpus now contains
zero control characters" was true and irrelevant — it measured the detector, not
the defect.

`c7f51dd` completes it. The lesson is recorded here because the failure mode is
general: **a scan that defines the defect by the symptom it happens to catch
will report clean while the defect persists.** The corruption was eventually
found by an unrelated survey of header emoji, not by the check written for it.

### What changed in the measurements

| measure | fork point | now | note |
| --- | ---: | ---: | --- |
| total agents | 270 | 270 | unchanged |
| total body words | 502,635 | 502,634 | −1: the orphaned `=` token (see below) |
| total bytes | 3,826,041 | 3,825,747 | −294 |
| stem ≠ name-slug | 198 | 198 | unchanged |
| duplicate stems / name-slugs | 0 / 0 | 0 / 0 | unchanged |

The byte count **fell** despite adding 48 newlines: removing the healthcare
files' alignment whitespace and their folded line breaks reclaimed more than the
newlines, quote characters and wider emoji added.

Body words fell by exactly one. In `marketing-app-store-optimizer` the
corruption's lost byte was `0x0A`, so it had inserted a real line break:

```
## =
 Market Analysis
```

— a title-less header with its text orphaned as body prose. Rejoining it into
`## Market Analysis` removes the stray `=` token. That is the only word-count
change in the entire step, and it is a structural repair rather than an edit.

All ten corpus-diversity dimensions are **numerically identical** to the fork
point (`duplicated_word_pct` 0.061, `shared_blocks` 11, `max_pct` 4.7377,
`mean_of_max` 0.2074, `median`/`p95` 0.0, `p99` 0.0635, `mean_words` 1754.0,
headers ≥50% 9, ≥75% 1). That is the expected result for repairs that touch
encoding and whitespace rather than content, and it is a useful negative
control: a "cleanup" that moved these numbers would not have been a cleanup.

### What did NOT change

- No filename.
- No `name` **value** — only leading alignment whitespace was stripped from
  three of them, which `slugify` was already discarding. Every `name_slug` is
  byte-identical, so no generated output path moved.
- No `color`, `emoji`, or `vibe` value, except the sovereign-health-systems
  `vibe`, which regained a sentence the parsers had been truncating.
- No body prose. For the three healthcare files the whitespace-separated token
  list is identical before and after; only line breaks moved.
- `divisions.json`, `tools.json`, `strategy/runbooks.json`: untouched.

### Verification at the time of the move

`lint-agents.sh` 0 errors / 58 warnings across 270 files; `check-divisions`,
`check-tools`, `check-runbooks`, `check-hermes-plugin` all PASSED; full
originality audit PASSED; diversity gate PASSED on all 10 dimensions;
`tests/test_corpus_diversity.py` 7/7.

The 58 lint warnings are pre-existing structural debt (29 agents lack a "Core
Mission" header, 24 lack "Critical Rules", 5 lack "Identity") and were not
touched here — changing agent structure is a content decision, not a
correctness repair.
