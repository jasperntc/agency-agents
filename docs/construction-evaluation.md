# Construction evaluation

**Does the agent file make the code better?**

Phase 7's first half asked whether an agent file helps a model *find* a defect.
Across 36 blind subagents, 12 tasks, 40 planted defects and three tiers, the
answer was no: `none`, `current` and `flattened` all scored 37/40, and on the
niche tier the no-agent control scored 100%. That result is written up in
[behaviour-evaluation.md](behaviour-evaluation.md).

It is also a narrow result. An agent that spots every bug and writes terrible
code scores perfectly there. This half asks the other question, which is the
one the corpus is actually for: **build this**.

Harness: [`scripts/eval_construction.py`](../scripts/eval_construction.py).

---

## The design

Each task is a **brief** plus an **acceptance suite the answerer never sees**.
The answerer writes one module to a given path. The suite is then run against
it and every check is scored.

Every check is classified once, when it is written, and the two classes are
never blended:

| kind | meaning | role |
|---|---|---|
| `stated` | the brief says it | the **floor** |
| `implied` | a competent practitioner in that domain meets it unasked | the **discriminator** |

### Why the split is the whole instrument

A construction test fails silently in a specific way: if the brief spells out
every requirement, all three conditions satisfy all of them and the experiment
measures nothing. The discriminator therefore has to be the requirements the
brief cannot state without giving away the answer:

- pagination that still returns each row exactly once after a newer row is
  inserted between pages — the reason keyset paging exists, and something
  offset paging fails while passing every other check
- a merge that is idempotent when the same batch is replayed
- a pseudonym that cannot be base64-decoded back into the email
- the Slavic teen exception, where `n % 10 == 1` is true for 11
- a token signature that covers the expiry, not just the subject

`stated` is not decoration. It is what makes the `implied` number readable: if
the stated rate is not near ceiling in every condition, the answers are bad for
reasons that have nothing to do with the agent file, and no implied comparison
from that run means anything.

### The conditions

| condition | what it gets |
|---|---|
| `none` | the brief, and nothing else — **the control** |
| `current` | the brief, plus the agent file as it ships |
| `flattened` | the brief, plus a generic agent file, real frontmatter, specialist body stripped — **the positive control** |

`none` is the control because an agent file that does not beat *no agent file*
is decoration however well it reads. `flattened` is the positive control
because if it scores like `current`, the instrument cannot see agent quality
and no result from it means anything. Its body is imported directly from the
behaviour harness so the two phases cannot drift apart and quietly stop being
comparable.

Both agent-file conditions are delivered identically — a file to read at a
path. Handing one condition a path and another inline text would measure the
delivery mechanism instead of the file.

---

## The six tasks

| task | agent | module | why this domain |
|---|---|---|---|
| c001 | `engineering-payments-billing-engineer` | `proration.py` | money arithmetic has strong unwritten conventions |
| c002 | `engineering-api-platform-engineer` | `pagination.py` | offset paging passes everything stated and breaks on insert |
| c003 | `engineering-data-engineer` | `loader.py` | replay, in-batch duplicates, out-of-order delivery |
| c004 | `engineering-privacy-engineer` | `pseudonymise.py` | the brief says what a pseudonym is *for*, never what it must resist |
| c005 | `engineering-i18n-engineer` | `plurals.py` | a named public standard with famous edge cases |
| c006 | `engineering-identity-access-engineer` | `tokens.py` | what a signature must *cover* is never stated |

Eight checks each — four `stated`, four `implied` — for 48 checks per
condition and 144 per full run.

---

## Blindness

The answer key here is the acceptance suite, and an answerer with repository
access can read anything committed. So:

- `eval/construction/tasks.jsonl` carries the **question only**: id, agent,
  module name, brief. No requirement text, and not the word *implied*.
- The suites, the reference implementations and the naive drafts were written
  **first**, kept outside the working tree while the answers were collected,
  and moved in afterwards. So was the harness itself, whose docstring describes
  the method.
- Each task records `suite_sha256_at_registration`, so pre-registration is
  **checkable** rather than merely claimed. A suite amended later is disclosed
  in the report rather than blocked — locking it would force a broken check to
  stay broken, and the Phase 7 oracle was rebuilt twice, correctly, both times.
- A test asserts no brief contains any word from a per-task leak vocabulary, and
  another asserts no committed artifact names any check id.

---

## Where generated code runs

This was the question that made Phase 7 choose planted defects in the first
place. The answer:

```
--execute   LOCAL, opt-in. One subprocess per artifact, isolated mode, a
            scratch working directory, a wall-clock timeout. Writes per-check
            outcomes to eval/construction/results/, each row carrying the
            sha256 of the artifact it ran and of the suite it ran.

--check     CI. Reads those committed results, re-verifies both digests against
            the committed bytes, re-scores. It never imports an artifact.
```

So scoring stays a pure function of committed data — the property that lets
`--check` run free — and public CI never executes generated code.

The honest limit, stated plainly: `--check` proves the recorded results belong
to *these* bytes, not that re-running would reproduce them. Reproducing them is
what `--execute` is for, and unlike re-running the models it costs seconds.

`scripts/lib/run_suite.py` is the only file in the repository that imports
model-generated code. It is a separate process so that an artifact which loops,
allocates, or raises at import takes down the runner and not the harness — and
so the harness records that outcome as the result instead of crashing with it.
It is **not** a sandbox, and the docstring says so.

---

## Calibrating the instrument before trusting it

Two failure modes have both already happened in this repository, and each gets
its own committed guard.

**The author of a fixture does not know what is wrong with it.** The Phase 7
pilot found four real defects in code its own key asserted was clean. So every
task has a **reference implementation**, and `--self-test` runs every suite
against it. A check a competent implementation fails is a broken check, and
this is the only way to learn that before the run rather than from the results.

**A check can be green while measuring nothing.** This project has shipped five
of those. Satisfiability is only half the proof, so every task also has a
deliberately **naive draft** — the version someone writes having read the brief
and thought about nothing else — and `--calibrate` asserts two things pointing
in opposite directions:

- every `stated` check **passes**, so the floor is genuinely reachable
- at least one `implied` check **fails**, per task, or that task cannot
  separate the conditions and is noise

Measured before any answers were collected:

| | stated | implied |
|---|---|---|
| reference | 24/24 | 24/24 |
| naive draft | **24/24** | **11/24** |

The naive draft clears the floor completely and loses 13 of 24 implied checks.
That is the dynamic range the run has to work in: a difference between
conditions, if one exists, has room to show up.

Both assertions run in CI as tests, not as something a maintainer remembers to
do by hand.

---

## The run

Two arms, one per model. `2026-08-18-subagent-c6` (Opus) is described first
because it was run first; the Sonnet arm that followed is below it and is what
settles how either should be read.

### Arm 1 — `claude-opus-5`

`2026-08-18-subagent-c6`. Eighteen blind subagents — 6 tasks × 3 conditions —
each writing one module to a given path, with no knowledge of how it would be
graded. Model: `claude-opus-5`.

That model is recorded in the run itself, not only here. A run is one model's
answers, so two runs are two arms, and an arm whose model is unrecorded cannot
be read — a lift figure means nothing without knowing what produced it. The run
name is a label rather than a record: this one says nothing about Opus. So
`--execute` requires `--model`, `--check` fails any run missing it, and the
operator asserts the value, which nothing in the harness can verify.

| condition | stated | implied | modules that import | implied vs `none` |
|---|---|---|---|---|
| `none` | 24/24 (100%) | 24/24 (100%) | 6/6 | — |
| `current` | 24/24 (100%) | 24/24 (100%) | 6/6 | **+0.0** |
| `flattened` | 24/24 (100%) | 24/24 (100%) | 6/6 | **+0.0** |

144 checks executed, 72 stated and 72 implied, 18 of 18 modules importing
cleanly. **Every condition passed everything.**

### Arm 2 — `claude-sonnet-5`

`2026-08-20-sonnet-c6`. The same six committed tasks, the same three
conditions, the same suites, eighteen more blind subagents. Nothing was rebuilt
for it: `tasks.jsonl`, the suites and both calibration sets were already
committed, so the only new inputs are the artifacts.

It exists because Arm 1 answered nothing. With `none` already at 24/24 there
was no headroom for an agent file to show in, and a **+0.0** lift measured
against a ceiling is not a null result — it is an absent measurement. The
stated objection was that `claude-opus-5` is simply strong enough not to need
help. A weaker model, the prediction went, would drop below ceiling on
`implied`, and the `current`-vs-`none` comparison would finally carry
information.

| condition | stated | implied | modules that import | implied vs `none` |
|---|---|---|---|---|
| `none` | 24/24 (100%) | 24/24 (100%) | 6/6 | — |
| `current` | 24/24 (100%) | 24/24 (100%) | 6/6 | **+0.0** |
| `flattened` | 24/24 (100%) | 22/24 (91.67%) | 6/6 | **-8.33** |

**The prediction failed.** `none` did not drop. Sonnet, with no agent file at
all, met every stated requirement and every implied one — the same ceiling as
Opus, on the same tasks, including the discriminators the naive draft fails.

So the honest reading of this axis is not "agent files do not help writing
code." It is:

> **These six tasks are too easy for frontier models.** Two model tiers clear
> every implied check with nothing but the brief. Until a construction task
> exists that a bare frontier model fails, this instrument cannot detect an
> agent file's contribution in either direction.

That is a finding about the tasks. It was the stated limitation of Arm 1, and
Arm 2 was the attempt to remove it; the attempt did not work, which promotes
the limitation from *caveat* to *result*.

#### The one cell that moved

`flattened` c001 (proration) scored 6/8 — the only non-ceiling cell across 36
subagents. It was hand-audited before being written down, because the one
number that moves in an otherwise flat matrix is the one most likely to be
over-read.

Both failures have a **single root cause**: the answer treated `period_end` as
the *inclusive* last billed day (`total_days = (period_end - period_start).days
+ 1`), while the suite assumes the *exclusive* convention. The brief pins the
period **start** behaviour explicitly and never says which end convention
applies.

| check | why it failed |
|---|---|
| `i_period_end_is_zero` | under the inclusive reading one day of the new plan remains on the last day, so it charges 65 cents rather than 0 |
| `i_symmetric_rounding` | fails the check's **secondary** assertion — distance from exact, which the convention shifts by up to 30.7 cents on the last day |

The property `i_symmetric_rounding` is named for **holds**: the module's
round-half-away-from-zero is exactly symmetric, `proration(A→B) == -proration(B→A)`
for all thirty days, verified by hand. The check failed on the closeness
assertion bundled with it, not on symmetry.

One artifact, one ambiguous convention, two checks keying off it, n=1. It is
recorded because it is the only movement in the matrix, and explicitly **not**
offered as evidence that a generic agent file degrades output. A second suite
amendment is not proposed either: the convention question is a real gap in the
brief, and rewriting the brief after seeing the answers is fitting the question
to the data.

### What this does and does not establish

It **does** establish that the ceiling is not a trivial one. The naive draft —
written from the same brief, thinking about nothing else — clears the stated
floor completely and still loses 13 of 24 implied checks. Nothing about these
tasks makes the implied requirements automatic. The no-agent control
nonetheless met all of them: exact integer money with symmetric rounding,
keyset cursors stable under a head insert, idempotent replay, HMAC under a
key derived from the salt rather than a reversible encoding, the Slavic teen
exception, a signature covering the expiry.

It **does not** establish that an agent file cannot help, because at 100% there
is no headroom in which it could show. Neither arm can separate *"the agent
file adds nothing"* from *"these tasks were too small to need it"* — and after
Arm 2 that is no longer a caveat awaiting a test, it is the result. What both
arms rule out is the specific hypothesis the phase was built on: that the base
model writes naive code which a specialist file corrects. Neither model writes
naive code here.

That is a sharper limitation than Phase 7's, where `none` scored 37/40 and
there was genuine room to beat it. Read together:

| axis | model | tasks | result |
|---|---|---|---|
| diagnosis (Phase 7) | `claude-opus-5` | 12, three tiers | 37/40 each — zero separation, **with headroom** |
| construction, Arm 1 | `claude-opus-5` | 6 | 48/48 each — zero separation, **at ceiling** |
| construction, Arm 2 | `claude-sonnet-5` | 6 | 48/48 `none` and `current` — zero separation, **still at ceiling** |

**72 blind subagents across two axes and two model tiers, and the agent file
has never yet moved a number upward.** On the diagnosis axis that is a null
with headroom, which is real evidence. On the construction axis it is a ceiling
on both tiers, which is an instrument that has not yet been given a hard enough
question.

## c007 — an attempt to build headroom, which did not work

Both arms ceilinged, so the axis is blocked on task difficulty rather than on
model choice. c007 is the first attempt to unblock it, and it is written up
here because **it failed to do so** and that is the useful part.

### The design, and the reasoning behind it

The diagnosis of why c001-c006 ceiling: every one of their implied checks is a
**named** best practice — keyset pagination, idempotent replay, HMAC over a
derived key, the Slavic teen exception. Frontier models recall named practices
very well. So c007 was built to have no name to recall, only calendar case
analysis:

> `renewals(start, count, every_months=1)` — the next `count` renewal dates
> for a subscription that began on `start`.

The invariant is that the anchor is `start.day`, kept forever, clamped per
month and **never written back**. Two plausible implementations get it wrong in
opposite directions:

| failure | what it does | what it produces |
|---|---|---|
| **drift** | computes each date from the previous one | Jan 31 → Feb 28 → Mar **28** |
| **sticky** | infers "end of month" from a start on the 30th | Apr 30 → May **31** |

Four implied checks probe it: month-end non-drift, the last-day-is-not-sticky
case, a leap anchor that must return to Feb 29 in 2028, and a calendar-months
check that `timedelta(days=30)` fails.

The two-sided calibration holds: the reference passes 8/8, and the naive draft
clears the stated floor 4/4 while failing 2 of 4 implied checks.

### Eight blind probes, and the ceiling again

Before registering c007 as a real arm, it was probed with **eight blind
subagents on `none` only** — four `claude-opus-5`, four `claude-sonnet-5` — with
the suites, references, naive drafts, harness, prior artifacts, results and
`tasks.jsonl` all moved outside the working tree.

| model | stated | implied | fully correct |
|---|---:|---:|---:|
| `claude-opus-5` | 16/16 | **16/16 (100%)** | 4/4 |
| `claude-sonnet-5` | 16/16 | **16/16 (100%)** | 4/4 |

**Every probe passed every check.** The scoring path was verified in the same
run — the reference scored 8/8 and the naive draft 6/8 through it, so the
checks were live and discriminating while the answers were perfect.

The models are not pattern-matching a remembered idiom. One probe's own
docstring reasons it out unprompted:

> *"A subscription begun on January 31st renews February 28th, then March 31st
> again, not March 28th. Each renewal is computed from the start date rather
> than from the previous renewal, so the clamping never accumulates."*

### What this adds

The hypothesis behind c007 — that removing the *name* removes the recall
advantage — is **wrong**, or at least insufficient. Month-end anchoring is
unnamed and still known cold by both tiers.

So the count is now **44 blind subagents on construction across two model
tiers, and `none` has never once dropped below ceiling.** The task set gains a
seventh task with a measured ceiling rather than measured headroom, which is
honest but is not the fix the axis needs. What would be needed is a task where
the correct answer requires knowledge these models demonstrably do not already
have — and three attempts have now failed to find one in the
single-module-from-a-brief format. That format may simply be the wrong
instrument for this question.

### A blindness hole this found, which predates it

Registering c007 required grepping the tree for leaks, and that turned up one
that had been there since the phase was built: **every task carried a `why`
field in `tasks.jsonl`, and `why` names the discriminator.**

    c002: "Offset paging satisfies every stated requirement and breaks the
           moment a row is inserted."

That is the implied check in one sentence, in the question file, in a public
repository the answering subagents could read. The blindness guard in `tests/`
inspected the `brief` only, so nothing caught it.

`why` now lives in the suite as `WHY_THIS_TASK`, with the rest of the answer
key, and a test asserts it never returns to `tasks.jsonl`.

**What this does and does not cast doubt on.** Both committed arms were
collected while the hole was open, so their blindness cannot be asserted as
cleanly as it was. It is a genuine weakening of the claim, and it is recorded
rather than argued away. Two things bound it: nothing in a subagent's task
pushed it to open `tasks.jsonl` — the prompt gives the brief inline and names
one output path — and the c007 probe above, run with `tasks.jsonl` withheld,
ceilinged exactly as the arms did. The ceiling therefore does not depend on the
hole. It remains the case that a result gathered under a leak is worth less
than one gathered without it.

### Suites amended after registration

Four of the six suites were corrected after the artifacts were collected, and
the report discloses this by comparing each suite against
`suite_sha256_at_registration`. Every amendment fixed a fixture that punished a
correct answer, and every one of them **raised** scores — that is, each worked
*against* finding an effect, never toward one:

| suite | what was wrong | effect |
|---|---|---|
| c001 | rejection accepted only `ValueError`; a module raising its own `BillingError` would have been scored as failing | none — c001 was already 8/8 everywhere |
| c002 | required an oversized `limit` to be clamped, when refusing it is equally correct | `flattened` 7/8 → 8/8 |
| c004 | the test salt was six characters; **all three conditions correctly refused it** | 0/8 → 8/8 in all three |
| c006 | the test secret was 28 characters against a 32-byte minimum, and the TTL check used a 100,000-second lifetime that also punished any sane maximum-lifetime policy | `flattened` 0/8 → 8/8 |

c004 is the one worth dwelling on. Three independent implementations refused a
weak salt, and the answer key called all three wrong. That is the Phase 7
lesson arriving again on a different axis: **the author of a fixture does not
know what is wrong with it.** The `--self-test` and `--calibrate` guards did
not catch this, because the reference and naive implementations were written by
the same hand and neither enforced a minimum salt length either. Only the real
answers exposed it.

### Verifying the result rather than believing it

A perfect score is exactly the shape of result that needs checking, so the
pipeline was audited end to end on a real artifact: the Russian teen exception
was deleted from a copy of the `none` c005 module — one line — and re-executed.

```
none  c005  7/8      <- the injected defect, caught
none  c001  8/8      <- untouched, unchanged
```

The detection is live, precise and localised. 144/144 is a measurement, not a
suite that passes everything put in front of it.
