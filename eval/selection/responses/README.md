# Recorded selection runs

One JSON file per run. Each records what a model picked for each case, plus
enough provenance to know what produced it.

```json
{
  "runner": "subagent",
  "model": "claude-opus-5",
  "scope": "pilot-15",
  "recorded_at": "2026-08-15",
  "tasks_sha256": "<sha256 of the task text this run answered>",
  "notes": "Blind subagents, one per case, no access to expected answers.",
  "picks": {
    "c001": { "agent": "gis-cartography-designer", "queries": ["colour ramp", "cartograph"] }
  }
}
```

| field | meaning |
| --- | --- |
| `runner` | `subagent` (a Claude Code session) or `api` |
| `model` | the model that answered — this is the thing under test |
| `scope` | `full`, or a label like `pilot-15` for a partial run |
| `tasks_sha256` | sha256 of the `task` text **this run answered**, as it was when the picks were collected |
| `picks` | case id → `{agent, queries}`. `"NONE"` records an honest miss |

## Why the hash is not optional

`scripts/eval_selection.py` refuses to score a file whose `tasks_sha256` no
longer matches. Picks are answers to specific questions; scoring them against an
edited benchmark silently re-attributes them to questions that were never asked.
That failure is invisible in the output — the accuracy number just changes — so
it is a hard error rather than a warning.

Get the value for a full run, or for the exact cases a partial run answered:

```bash
python3 scripts/eval_selection.py --digest
```

```bash
python3 scripts/eval_selection.py --digest c001 c002 c003
```

## Why it hashes the tasks and not the file

It hashed the whole `cases.jsonl` first. That was wrong, and the reason is worth
keeping: a blind runner sees **only the task text** — never `expect`, never
`why`, never `kind`. Binding picks to fields the runner could not have seen means
that fixing one wrong expected answer destroys 58 valid picks and forces a full
re-run. A guard that expensive is an argument for leaving a known-wrong benchmark
in place, which is the opposite of what it is for.

So the digest covers sorted `(case id, task)` pairs, restricted to the cases the
run actually answered:

| change | effect on a recorded run |
| --- | --- |
| correcting `expect` or `why` | none — the question is unchanged |
| rewording a `task` | **invalidated**, for runs that answered it |
| adding a case | none — the run stays valid, just incomplete, and `cases_missing` says so |
| deleting a case | invalidated; the ratchet on `cases.total` should prevent this anyway |

This guards against *silent* re-attribution, not against a determined editor —
anyone can recompute the value and paste it in. The point is that it cannot
happen by accident and that a deliberate change leaves a diff.

## Blindness

Whoever answers must not see `expect`, `why`, or `kind`. Generate each prompt
with `./scripts/eval_selection.py --prompt <case>` — it emits the task text and
nothing else. A run collected any other way should say so in `notes`, and its
numbers should be read as an upper bound rather than a measurement.

These files are append-only in spirit: a recorded run is evidence about a
particular model on a particular day. Add new files rather than editing old ones.
