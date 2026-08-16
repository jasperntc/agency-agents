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
