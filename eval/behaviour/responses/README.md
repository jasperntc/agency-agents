# Recorded behavioural runs

One JSON file per run. Answers are grouped by **condition**, then by task.

```json
{
  "runner": "subagent",
  "model": "claude-opus-5",
  "recorded_at": "2026-08-16",
  "tasks_sha256": "<from ./scripts/eval_behaviour.py --digest>",
  "notes": "Blind subagents, one per (task, condition). None saw planted or clean.",
  "answers": {
    "none":      { "b001": "FINDING: ...\nDONE: 3" },
    "current":   { "b001": "FINDING: ...\nDONE: 4" },
    "flattened": { "b001": "FINDING: ...\nDONE: 2" }
  }
}
```

Answers are stored **verbatim**. Scoring is a pure function of
`(tasks, fixtures, answers)`, so a recorded run is re-scoreable forever — and
re-scoreable under *corrected* phrasing lists, which is the point of binding the
digest to the question rather than the answer key.

## Blindness

Whoever answers must never see `planted`, `clean`, or `why`. Generate each
prompt with `--prompt <task> --condition <condition>`; it emits the task, the
fixture, and the output contract, and nothing else.

The conditions must be answered by **separate** agents with clean context. One
agent answering the same task twice has already seen the file, and the second
answer is not a measurement of anything.

## The order matters less than the isolation

There is no requirement to run `none` first. There *is* a requirement that no
answerer has seen another condition's answer, or the fixture, or this directory.
