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

## Recall alone would be a trap

An answer listing twenty possible problems hits the planted one by accident.
That is the same failure as OR-ing every word in the routing harness: widen the
answer and the hit rate rises for free.

The first design answered this with `clean` aspects — code asserted to be
correct, where a claim was a false claim. **It did not survive its own pilot**,
and the replacement is `defect_density` rather than a precision score. Both are
explained under [Precision was dropped, not fixed](#precision-was-dropped-not-fixed).

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

## The oracle is a line number

No model decides whether a finding "counts" — that would put rung 4 evidence
where rung 1 belongs and make every score depend on a second model nobody
calibrated. But the first attempt at a literal oracle matched **prose** against
hand-written phrasing lists, and the pilot below destroyed it.

Three traps were caught by `tests/test_eval_behaviour.py` before any answer was
collected, and they are worth keeping because they are the shape of the problem:

- **`Sum(`**, listed as a phrasing for "aggregate in the database", matched the
  fixture's own `sum(o.total_cents ...)` — so quoting the *broken* line scored as
  recommending the fix.
- **`SQLi` matched inside `sqlite3`**, so mentioning the import scored a SQL
  injection find.
- **`key={index}` is a literal token of the defect**, so matching it could not
  distinguish diagnosis from quotation.

Fixing all three left the oracle still fundamentally unsound, which the pilot
then demonstrated. Scoring is now by **location**: every `FINDING` carries
`L<line>`, and a defect is found when a cited line falls in its range.

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

- **Blindness held**, on the evidence of the transcripts: no subagent read the
  answer key, every answer was attributable, and the output contract was
  followed in 12 of 12 — better than the selection pilot managed. Read that as
  an observation, not a guarantee: until 2026-08-20 the key was *reachable*.
  See [The leak this could not have caught](#the-leak-this-could-not-have-caught).
- **A depth gradient exists**, visible by eye rather than by score: on `b004`,
  `current` produced 11 findings, `flattened` 7, `none` 3, and the extra ones are
  real (idempotency, missing auth, connection exhaustion on the sold-out path).
  Whether depth is *quality* is precisely what a working precision measure would
  settle, and this run had none.

### The fix, now built

Scoring is by **location, not wording**. Every `FINDING` must carry
`L<line>`; a planted defect counts as found when a cited line falls in its
range. Line numbers are unambiguous, need no phrasing list, and leak nothing —
the fixture is shown numbered so citing costs no counting, and every line gets a
number so the numbering marks nothing.

**The twelve pilot answers could not be re-scored.** Only 3 of 12 cite any line,
because the old prompt never asked. Scoring them under the new oracle would give
nine of them 0 found — an artifact of the old contract that would read as a
result. `tasks_digest` now covers `PROMPT_TEMPLATE` for exactly this reason; it
did not, which was a real defect, and without the fix those answers would have
been silently re-scored.

The run is kept in place, marked `superseded` with a written reason, and
excluded from scoring rather than deleted. It is the evidence that invalidated
the first oracle.

### Precision was dropped, not fixed

`clean` aspects are gone. Two findings killed them: the measure never fired once
across 12 answers, and the pilot found four real defects in code the key had
asserted was clean — two of them *inside* `clean` aspects.

The second generalises. **The author of a fixture does not reliably know what is
wrong with it.** A precision measure built on a complete defect inventory
inherits that, and one that punishes an answer for being right about an unlisted
defect is worse than none.

What is reported instead is cost, not correctness:

| | |
| --- | --- |
| `recall_pct` | planted defects whose line was cited — **the scored metric** |
| `lines_cited` | distinct lines pointed at |
| `defect_density` | `found / lines_cited` — a scattergun answer scores badly |
| `contract_pct` | findings carrying a line, over findings declared |

`defect_density` makes padding visible without claiming the extra citations are
wrong. Read it like `effort_tool_calls` in the selection harness.

The four unplanted defects were promoted into `planted`, so the recall
denominator now matches what is actually in the fixtures.

## The second pilot (2026-08-16, v2): the right answer, for the wrong reason

12 blind subagents under the line-citation contract. Recorded in
`eval/behaviour/responses/2026-08-16-subagent-pilot12-v2.json`. Output contract
held **12 of 12**, against 12 of 15 in the selection pilot.

| condition | recall | lines cited | density | vs `none` |
| --- | ---: | ---: | ---: | ---: |
| `none` | 10/13 (76.92%) | 15 | 0.667 | |
| `current` | 12/13 (92.31%) | 15 | 0.800 | **+15.39** |
| `flattened` | 11/13 (84.62%) | 13 | 0.846 | +7.70 |

That is exactly the shape this phase was built to detect: the real agent ahead of
both controls, in the right order, with the generic control in between. **It is
an artifact, and every point of it dissolves under a hand audit.**

### Auditing each scored miss against what the answer actually says

| cell | scored miss | what the answer says | verdict |
| --- | --- | --- | --- |
| `b004/none` | race (key L22–27) | "**L21**: The check-then-insert … is a TOCTOU race" | artifact |
| `b002/none` | negative limit (key L14) | "**L13**: … and negative values are not rejected" | artifact |
| `b002/flattened` | negative limit (key L14) | "**L13**: … non-numeric **or negative** value … bypasses the intended bound" | artifact |
| `b004/*` | `bool` guard (key L14) | not mentioned by any condition | **genuine** |

Credit the three artifacts and every condition lands on **12/13, 92.31%**. No
separation whatsoever. Each one missed exactly the same single defect.

### The two mechanisms, both mine

- **Granularity.** A reviewer writes one finding covering two adjacent defects —
  "`int()` is unguarded **and** negative values are not rejected" — because that
  is how people write. The key splits them across L13 and L14, so one is scored
  a miss. The answer key's granularity and a human's are different things.
- **Deduplication.** `b004/none` filed two distinct findings at L21. `cited_lines`
  dedups, so the second is erased before scoring. That was my choice, made to
  stop a repeated citation inflating `lines_cited`, and it silently destroys a
  correct diagnosis instead.

### Why this is worse than the v1 failure

The v1 pilot produced an obviously wrong answer — the generic control beating the
real agent by 25 points — so nobody could have acted on it. **This one produced
the expected answer.** A run that confirms the hypothesis is the one least likely
to get audited, and it took a line-by-line reading to find that the entire
margin was mechanical.

Two pilots, two headline numbers, both artifacts. The instrument is not yet
measuring agent quality; it has so far only measured its own defects — which is
what pilots are for, and is also the reason no behavioural number from this
repository should be quoted yet.

### What the run does establish

- **The contract works.** 12/12 compliance, and `contract_pct` is now a live
  metric that would expose any drop.
- **Line citation beat prose matching.** The v1 oracle scored the control above
  the real agent; v2 at least ordered them plausibly, and its errors are
  identifiable by reading rather than invisible.
- **Three of four tasks are at full recall in every condition.** `b001` 3/3,
  `b003` 4/4 across the board. These fixtures cannot separate conditions because
  the defects are too findable — the selection benchmark's ceiling problem,
  arriving in a new phase within a day.
- **On these tasks the agent files add nothing detectable.** That is a real,
  if narrow, negative finding, and it is confounded by the ceiling above, so it
  is not yet evidence that the agents are worthless. It is evidence that four
  easy fixtures cannot tell.

### What has to change before a third run

Harder fixtures, where a non-specialist plausibly misses something a specialist
catches; the `bool`/`int` guard is the only defect in this set with that
property, and every condition missed it. And a scoring rule that survives normal
human phrasing — most likely crediting a defect when *any* cited line falls
within a small window of it, with the window recorded per defect rather than
inferred.

## Two tiers, because an easy benchmark cannot separate anything

The v2 pilot put three of four tasks at full recall in **every** condition. A
benchmark like that is not measuring the agent; it is measuring whether the
defect is famous.

| tier | tasks | defects | what a defect requires |
| --- | ---: | ---: | --- |
| `easy` | 4 | 12 | recognising a well-known anti-pattern — N+1, SQL injection, index keys, check-then-act |
| `hard` | 4 | 13 | knowing a specific rule, in code that looks correct |

The hard tier was built around the one defect in the easy tier that **every**
condition missed: `isinstance(True, int)` is `True`, so a boolean passes an
integer guard. That is the shape worth testing — code that reads as fine unless
you happen to know the rule.

| task | agent | defects |
| --- | --- | --- |
| `b005` | database-optimizer | `date_trunc` on an indexed column defeats the index; a `(tenant_id, created_at)` index cannot serve a `created_at`-only filter; `NOT IN` against a nullable column returns zero rows |
| `b006` | backend-architect | exponential backoff with no jitter synchronises every retrying worker; 40 connections × 12 processes against one database; `time.time()` where `time.monotonic()` is required |
| `b007` | frontend-developer | `debounce()` called during render debounces nothing; a non-lazy `useState` initializer runs every render; an object literal in a dependency array changes identity every render |
| `b008` | code-reviewer | `random` instead of `secrets` for a reset token; a 404 that enumerates accounts; `==` on a token digest; unsalted SHA-256 for password storage |

Recall is reported **per tier**, never blended. An easy tier at ceiling would
otherwise hide whatever the hard tier is doing — the same rule that governs
every other metric in this repository.

### The leak this could not have caught

Every run above was collected while `eval/behaviour/tasks.jsonl` carried the
**complete answer key in the same record as the prompt** — all 40 planted
defects with their ids, their exact line ranges, and a description of each:

    {"task": "b009", "prompt": "These catchment queries return the wrong
     stops...", "planted": [{"id": "distance_in_degrees", "lines": [[11, 14]],
     "what": "ST_Distance on 4326 geometry returns degrees..."}]}

Scoring here is *cite the line number*. That file was therefore not a hint at
the answer key, it **was** the answer key, sitting in a public repository the
answering subagents could read.

The guard that existed, `test_prompt_never_carries_the_answer_key`, checks the
**rendered prompt**. It passed the whole time and was never wrong — it was
answering a narrower question than the one that mattered. The thing to check is
what an answerer can *reach*, not what it was *handed*.

### What it does and does not cast doubt on

It weakens the blindness claim on all three recorded runs, and that is stated
rather than argued away. Two things bound it:

- **The scores are inconsistent with exploitation.** A subagent reading
  `tasks.jsonl` scores 40/40 trivially, because the file lists the lines it
  would need to cite. The run scored **37/40**, and three defects went unfound
  by *every* condition. A leak that was actually used does not leave misses
  behind, and certainly not the same misses in all three arms.
- **Nothing in the task pushed a subagent toward the file.** The prompt carries
  the numbered fixture inline and asks a question about it; there is no reason
  to open `eval/behaviour/` at all.

So the likeliest reading is that the door was unlocked and nobody walked
through it. That is still worth less than a door that was locked.

### The fix

The question and the key are now separate files:

| file | holds | during a run |
|---|---|---|
| `eval/behaviour/tasks.jsonl` | id, agent, fixture, tier, prompt | stays |
| `eval/behaviour/key.jsonl` | `planted`, `why` | **moved out of the tree** |

`--prompt` renders from the questions alone and works with the key absent, so
the blind procedure is now possible rather than merely intended: render every
prompt, move `key.jsonl` out, collect, move it back, score. Scoring without the
key fails loudly instead of silently scoring nothing.

Three tests enforce it — the question file may not carry `planted`, `why` or
`clean`; the key must cover every question; and a prompt must render without
the key. The digest is unaffected: it was always taken over the question and
the fixture bytes, never over the expected answers, so this split re-scores
every committed run unchanged.

## Anchors, and why a defect may declare several

`lines` is a list of `[lo, hi]` ranges. Some defects have more than one
defensible home: a wall-clock timeout lives both where the timestamp is taken
and where the elapsed comparison happens; a stale dependency array lives both at
the literal that is rebuilt and at the array that consumes it.

Picking one and scoring the other a miss is exactly what produced the v2 pilot's
phantom 15-point separation. Declaring both is honest; widening the window until
anything nearby counts would not be, which is why the window is capped at 2 and
must be stated per defect.

## The hard tier (2026-08-16): still no separation, and now it means something

12 blind subagents over `b005`–`b008`. Contract held 12/12.

| condition | recall | lines cited | density | vs `none` |
| --- | ---: | ---: | ---: | ---: |
| `none` | 11/13 (84.62%) | 14 | **0.786** | |
| `current` | 11/13 (84.62%) | 18 | 0.611 | **+0.0** |
| `flattened` | 11/13 (84.62%) | 17 | 0.647 | **+0.0** |

Not merely the same totals. The **same defects, found and missed, task by task**:

| | `b005` | `b006` | `b007` | `b008` |
| --- | ---: | ---: | ---: | ---: |
| `none` | 3/3 | 2/3 | 3/3 | 3/4 |
| `current` | 3/3 | 2/3 | 3/3 | 3/4 |
| `flattened` | 3/3 | 2/3 | 3/3 | 3/4 |

Both misses are uniform. Every condition missed `time.time()` where `monotonic`
is required, and every condition missed `==` on a token digest. The agent file
did not help on the two defects that were actually hard.

### Combined across both tiers

**24 blind subagents. 8 tasks. 25 defects. Three conditions. Zero separation,
anywhere.** `none` 22/25, `current` 22/25, `flattened` 22/25.

### Density runs the wrong way

On the hard tier the control is the *most* precise: `none` 0.786 against
`current` 0.611. The agent-file conditions cite more lines for identical recall.
That is not evidence they are worse — the extra citations are largely real
defects — but it is the opposite of the direction a useful specialist file
should push, and it is the only dimension that moved at all.

### The finding

**On diagnostic code review, with `claude-opus-5`, these four agent files make
no measurable difference.** The base model already saturates the task. That is
a real, controlled negative result and it bears directly on Goal A.

It is not a claim that the corpus is worthless, and the limits are specific:

- **Diagnosis, not construction.** Nothing here measures whether an agent
  produces better code, only whether it spots defects.
- **One model, one sample per cell.** A weaker model might separate; two runs of
  this one would differ.
- **Four agents of 270**, chosen because rung-1 evidence exists for them.
- **The instrument is now trustworthy enough to believe a null.** Both known
  failure modes were fixed and then validated in this very run: `none` cited L14
  and `current` cited L28 for the same defect, and multi-anchor scoring credited
  both. Under the previous key that alone would have manufactured a difference.

### Seven defects the answer key does not list

Across three pilots the subagents found, in code this benchmark authored:

`?limit=-1` unbounded in SQLite · a `data-to` attribute never rendered ·
`count()` on rows not seats · `isinstance(True, int)` · a password reset that
accepts an empty password · 4xx swallowing retryable 429/408 · a claim `UPDATE`
with no `FOR UPDATE SKIP LOCKED` and no lease

All real. **The author of a fixture does not know what is wrong with it**, and
that is now established across three independent runs rather than asserted once.

## The niche tier (2026-08-16): the last hypothesis, also null

The hard tier failed to separate anything, so the remaining explanation was
**domain**: perhaps the base model is only saturated on mainstream engineering,
and a specialist file earns its place where training signal is thinner. Four
domains chosen on that basis — PostGIS spatial semantics, Cortex-M0+ firmware,
Solidity, and clinical trial methodology.

| condition | recall | lines cited | density | vs `none` |
| --- | ---: | ---: | ---: | ---: |
| `none` | **15/15 (100%)** | 15 | 1.000 | |
| `current` | 15/15 (100%) | 19 | 0.789 | +0.0 |
| `flattened` | 14/15 (93.33%) | 17 | 0.824 | −6.67 |

**The control scored 100%.** With no agent file, blind, it found every planted
defect: `ST_Distance` returning degrees, the non-sargable predicate, degree
buffers, square-degree areas, torn 64-bit reads, missing `volatile`, soft-float
in an ISR, a 1 KB stack frame on a 4 KB part, `tx.origin`, division-before-
multiplication, an unchecked `call`, the gas stipend, intention-to-treat,
censoring, and multiplicity.

`flattened`'s single miss is **not real**. On `b009` it wrote *"returns degrees,
not metres … and the predicate is also non-sargable so the GIST index is never
used"* — both keyed defects, correctly, in one sentence. Matching credits one
finding with one defect, so it scores 3/4 where `none` split the same content
across two lines and scored 4/4. Corrected, **all three are 15/15**.

That is the `b002` granularity error, which had already been diagnosed and fixed
once by merging the two defects, and which I then reintroduced in `b009` the
same day. It is recorded rather than silently repaired because the rate at which
this specific mistake recurs is itself the finding.

### Combined, across all three tiers

**36 blind subagents. 12 tasks. 40 defects. Three conditions. No separation
anywhere.**

| tier | `none` | `current` | `flattened` |
| --- | ---: | ---: | ---: |
| easy | 11/12 | 11/12 | 11/12 |
| hard | 11/13 | 11/13 | 11/13 |
| niche | 15/15 | 15/15 | 14/15 → 15/15 corrected |
| **total** | **37/40** | **37/40** | **37/40** |

### What is now established, and what is not

**Established.** On defect diagnosis, across mainstream and specialist domains,
with `claude-opus-5`, an agent file makes no measurable difference. The
"thinner knowledge" hypothesis was the strongest remaining explanation for the
hard-tier null and it does not survive: there is no thin domain here to exploit.

**Not established.** That the corpus is worthless. Every run measures
*diagnosis*, and the agent files may still shape *construction* — what gets
built, in what order, to what standard. Nothing here touches that. Nor does it
touch weaker models, longer tasks, or multi-step work where a standard has to be
held over time rather than applied once.

### The limitation the niche tier exposed in the oracle

Location-based scoring cannot tell **which** defect at a line was found, and this
run showed it cutting both ways on the same line. At `b011` L39, `current` named
the planted defect exactly — *"`transfer`, whose 2300-gas stipend also reverts"* —
while `none` and `flattened` cited L39 for an unplanted and more severe bug, the
sweep draining escrowed principal. All three scored identically.

So the oracle **over-credits** an answer that found something else at the right
line, and **hides** a real advantage when one condition is more precise there.
Prose matching failed worse, and no third option has been found that is both
deterministic and content-aware. It is a known, bounded cost, stated here rather
than left for a reader to discover.

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
