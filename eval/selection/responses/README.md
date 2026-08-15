# Recorded selection runs

One JSON file per run. Each records what a model picked for each case, plus
enough provenance to know what produced it.

```json
{
  "runner": "subagent",
  "model": "claude-opus-5",
  "scope": "pilot-15",
  "recorded_at": "2026-08-15",
  "cases_sha256": "<sha256 of eval/routing/cases.jsonl>",
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
| `cases_sha256` | sha256 of `cases.jsonl` **as it was when the picks were collected** |
| `picks` | case id → `{agent, queries}`. `"NONE"` records an honest miss |

## Why the hash is not optional

`scripts/eval_selection.py` refuses to score a file whose `cases_sha256` no
longer matches. Picks are answers to specific questions; scoring them against an
edited benchmark silently re-attributes them to questions that were never asked.
That failure is invisible in the output — the accuracy number just changes — so
it is a hard error rather than a warning.

Get the current value with:

```bash
python3 -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('eval/routing/cases.jsonl').read_bytes()).hexdigest())"
```

## Blindness

Whoever answers must not see `expect`, `why`, or `kind`. Generate each prompt
with `./scripts/eval_selection.py --prompt <case>` — it emits the task text and
nothing else. A run collected any other way should say so in `notes`, and its
numbers should be read as an upper bound rather than a measurement.

These files are append-only in spirit: a recorded run is evidence about a
particular model on a particular day. Add new files rather than editing old ones.
