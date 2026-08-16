# Behavioural evaluation

Every other gate in this repository measures **text**. Does an id match a
pattern, do two descriptions share shingles, can a grep reach the right agent.
None of them can say whether an agent's advice is any good — which the handoff
calls the central engineering problem, and which is why zero of the 270 agents
have been deliberately improved.

This measures one narrow, checkable piece of it.

```bash
./scripts/eval_behaviour.py                             # score recorded runs
./scripts/eval_behaviour.py --check                     # CI: baseline is current
./scripts/eval_behaviour.py --conditions                # what each condition is
./scripts/eval_behaviour.py --prompt b001 --condition none
./scripts/eval_behaviour.py --emit-controls             # regenerate the controls
```

## The three conditions are the whole design

| condition | what the answerer gets |
| --- | --- |
| `none` | the task and the file, nothing else |
| `current` | the same, plus the agent file as it ships today |
| `candidate` | the same, plus a proposed replacement agent file |
| `flattened` | the same, plus a **generic** agent file — positive control |

`none` is not a formality, it is **the control**. An agent file that scores the
same as no agent file at all is decoration, however well it reads, and no
amount of lexical validation would ever say so. The reported figure is therefore
never the raw score — it is `lift_over_no_skill`.

`flattened` answers the question the routing harness had to answer with a
constructed control: *can this instrument see agent quality at all?* If a generic
file scores like the real one, no result from this harness means anything. The
control keeps the real frontmatter and replaces only the body, so a score drop
cannot be blamed on a malformed file.

## Recall alone is a trap

An answer listing twenty possible problems will hit the planted one by accident.
That is the same failure as OR-ing every word in the routing harness: widen the
answer and the hit rate rises for free.

So every task also names **`clean` aspects** — things deliberately *correct* in
the fixture. Claiming one is a false claim.

```
found_pct   planted defects identified
false_pct   deliberately-correct aspects claimed as broken
lift        found_pct − false_pct
```

`lift` is the only figure comparable between conditions, for exactly the reason
`lift_over_control` is in [routing-evaluation.md](routing-evaluation.md).

In `b002` the SQL injection is real, and the `limit` is deliberately
parameterised **and** clamped, and the connection is closed in a `finally`.
A reviewer padding its list will claim one of those and pay for it.

## Why planted defects, and not "generate code and run the tests"

Running generated code is rung 1 of the handoff's evidence hierarchy too, but it
costs two things this project is not ready to spend. Scoring would stop being a
pure function of committed data — the only reason Phase 8's `--check` runs free
in CI — and public CI would be executing model-generated code.

A planted defect is checkable by matching alone: deterministic, free, reviewable
in a diff, no sandbox.

**The cost, stated plainly: this measures diagnosis, not construction.** An agent
that spots every bug and writes terrible code scores perfectly here. Extending
to generated-and-executed artifacts is the obvious next increment, and it needs
a sandbox story first.

## Matching is literal, and that is a deliberate choice

No model decides whether a finding "counts". A judge would put rung 4 evidence
where rung 1 belongs and make every score depend on a second model nobody
calibrated. The cost is that phrasing lists are maintained by hand — visible
work rather than invisible drift.

Two traps found while building this, both by
`tests/test_eval_behaviour.py` before a single answer was collected:

- **Substring matching scored `SQLi` inside `sqlite3`.** Any answer mentioning
  the import counted as finding a SQL injection. Matching now requires a word
  boundary at each alphanumeric end — and only at alphanumeric ends, so
  `.aggregate` and similar still fire, since a blanket `\b…\b` would make them
  silently never match, which is the worse failure.
- **A phrasing that is a literal token of the defect cannot distinguish
  diagnosis from quotation.** `key={index}` appears in the fixture, so matching
  it scored any answer that quoted the line. The surviving phrasings are all
  diagnostic language — *index as key*, *stable key* — which require describing
  the problem rather than echoing it.

A third was caught the same way: `Sum(` as a phrasing for "aggregate in the
database" matched the fixture's own `sum(o.total_cents ...)`, so quoting the
broken line scored as recommending the fix. Exactly backwards.

## The first pilot (2026-08-16) found the instrument invalid

12 blind subagents, 4 tasks × 3 conditions, `claude-opus-5`. Recorded in
`eval/behaviour/responses/2026-08-16-subagent-pilot12.json`.

| condition | found | false claims | lift | vs `none` |
| --- | ---: | ---: | ---: | ---: |
| `none` | 4/8 (50.0%) | 0/12 (0.0%) | 50.0 | |
| `current` | 5/8 (62.5%) | 0/12 (0.0%) | 62.5 | +12.5 |
| `flattened` | 7/8 (87.5%) | 0/12 (0.0%) | 87.5 | **+37.5** |

**The generic positive control beat the real agent by 25 points.** Do not read
that as a finding about the corpus. It is a finding about this harness, and the
pilot existed to produce exactly this kind of result before anyone acted on a
number.

### Defect 1 — matching measures phrasing, not diagnosis

`b001/current` and `b001/flattened` give the *same* diagnosis. One scored 3/3
and the other 1/3:

| | wrote | list had | scored |
| --- | --- | --- | ---: |
| `flattened` | "roughly **two queries per** customer", "**annotate**", "**GROUP BY**" | matched | 3/3 |
| `current` | "evaluates the same `orders` queryset twice", "letting the database compute `SUM(total_cents)`" | "evaluates the queryset twice", "let the database do the sum" | 1/3 |

Near-misses by one word. Three separate correct diagnoses of the index-key
defect in `b003` — "index-based in a reorderable list", "the key must be a
stable `task.id`", "binds React's element identity to position" — matched **none**
of the phrasings, all of which were written before any answer existed.

The deeper problem is that this is not fixable by adding phrasings. Widening the
lists to match the answers already collected is fitting the answer key to the
data, which is the trap this project exists to avoid. **Literal matching over
free-form prose is deterministic in computation and arbitrary in what it
recognises** — which is not the same thing as a rung-1 oracle, whatever the
original docstring claimed.

### Defect 2 — the precision half never fired

`false_pct` is **0.0% in every condition**. The `clean` aspects, which exist so
that padding an answer cannot pay, did not trigger once — even though
`b004/current` reported 11 findings against `b004/none`'s 3.

So `lift = found_pct − false_pct` collapsed to plain recall, and the control
that was supposed to make thoroughness cost something was inert for the entire
run. A metric that cannot move is indistinguishable from a metric that does not
exist, which is the same lesson as `pairwise.max_pct` in
[corpus-metrics.md](corpus-metrics.md).

### Defect 3 — the fixtures contain defects I did not plant

Four, found by the subagents:

| fixture | unplanted defect |
| --- | --- |
| `b002` | `if limit > 200` leaves `?limit=-1` untouched, and SQLite reads a negative LIMIT as unbounded |
| `b003` | `e.currentTarget.dataset.to` reads a `data-to` attribute that is never rendered, so every drag moves the row to the top |
| `b004` | `taken` counts reservation *rows*, not seats, so a 10-seat booking counts as 1 and the event oversells 10× with no concurrency at all |
| `b004` | `isinstance(True, int)` is `True`, so `{"quantity": true}` passes the "integer 1-10" guard |

Two of those sit **inside `clean` aspects** — code the answer key asserts is
correct. A correct finding could therefore be scored as a false claim, and the
recall denominator is wrong because the fixture has more real defects than the
key lists.

This is the most uncomfortable of the three, because it generalises: **the author
of a fixture does not reliably know what is wrong with it.** Any design that
assumes a complete defect inventory inherits that.

### What the run does say

Nothing about agent quality yet. Two things about the method:

- **Blindness held.** No subagent read the answer key, every answer was
  attributable, and the output contract was followed in 12 of 12 — better than
  the selection pilot managed.
- **A depth gradient exists**, visible by eye rather than by score: on `b004`,
  `current` produced 11 findings, `flattened` 7, `none` 3, and the extra ones are
  real (idempotency, missing auth, connection exhaustion on the sold-out path).
  Whether depth is *quality* is precisely what a working precision measure would
  settle, and this run had none.

### The fix being considered

Score on **location, not wording**: require every `FINDING` to cite a line
number, and check whether the planted defect's line is among those cited. Line
numbers are unambiguous, need no phrasing list, and leak nothing — the answerer
still has to find the line. Phrase matching would drop to a secondary signal, so
citing the right line for the wrong reason does not score.

That is a redesign of the oracle, not a widening of the lists, and it is
deliberately not applied to this run's numbers.

## What is bound to a run

`tasks_sha256` covers `(task id, prompt, sha256 of the fixture)` — the question
asked. Editing `planted` or `clean` is a **scoring** change and does not
invalidate recorded answers; editing a prompt or a fixture is a **different
question** and does. Same rule and rationale as
[selection-evaluation.md](selection-evaluation.md).

## What this does not measure

- **Construction.** Diagnosis only, as above.
- **Whether the fix is right.** A finding scores on naming the defect, not on
  proposing a correct repair.
- **Anything outside four engineering agents.** The slice was chosen because
  rung-1 evidence exists here, not because it is representative.
- **Variance.** One answer per task per condition. Two runs will differ.
