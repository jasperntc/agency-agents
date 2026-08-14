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

## Move 1 — 2026-08-14 — `upstream-baseline-2026-08-13` → `e4a0fbc`

Step 0.4, source-correctness repairs. **52 of 270 agent files changed** across
four separately revertible commits.

| commit | files | what |
| --- | ---: | --- |
| `71f5589` | 3 | healthcare: folded multi-line frontmatter, removed alignment padding |
| `121969d` | 1 | engineering-developer-tooling-engineer: quoted a description containing `": "` |
| `719747c` | 2 | repaired `0x04` mojibake in section headers |
| `e4a0fbc` | 48 | added a missing trailing newline |

(54 repairs across 52 files — `engineering-mobile-app-builder` and
`marketing-app-store-optimizer` appear in both the mojibake and newline commits.)

### What changed in the measurements

| measure | fork point | now | note |
| --- | ---: | ---: | --- |
| total agents | 270 | 270 | unchanged |
| total body words | 502,635 | 502,635 | **unchanged** — every repair was frontmatter or whitespace |
| total bytes | 3,826,041 | 3,825,813 | −228 |
| stem ≠ name-slug | 198 | 198 | unchanged |
| duplicate stems / name-slugs | 0 / 0 | 0 / 0 | unchanged |

The byte count **fell** despite adding 48 newlines: removing the healthcare
files' alignment whitespace and their folded line breaks reclaimed more than the
newlines, quote characters and wider emoji added.

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
