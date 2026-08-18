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

`2026-08-18-subagent-c6`. Eighteen blind subagents — 6 tasks × 3 conditions —
each writing one module to a given path, with no knowledge of how it would be
graded. Model: `claude-opus-5`.

| condition | stated | implied | modules that import | implied vs `none` |
|---|---|---|---|---|
| `none` | 24/24 (100%) | 24/24 (100%) | 6/6 | — |
| `current` | 24/24 (100%) | 24/24 (100%) | 6/6 | **+0.0** |
| `flattened` | 24/24 (100%) | 24/24 (100%) | 6/6 | **+0.0** |

144 checks executed, 72 stated and 72 implied, 18 of 18 modules importing
cleanly. **Every condition passed everything.**

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
is no headroom in which it could show. This run cannot separate *"the agent
file adds nothing"* from *"these tasks were too small to need it"*. What it
rules out is the specific hypothesis it was built to test: that the base model
writes naive code which a specialist file corrects. It does not write naive
code here.

That is a sharper limitation than Phase 7's, where `none` scored 37/40 and
there was genuine room to beat it. Read the two together and the picture is
consistent rather than merely repeated:

| axis | tasks | conditions | result |
|---|---|---|---|
| diagnosis (Phase 7) | 12, three tiers | none / current / flattened | 37/40 each — zero separation, with headroom |
| construction (here) | 6 | none / current / flattened | 48/48 each — zero separation, at ceiling |

**54 blind subagents across two axes, and the agent file has never yet moved a
number.**

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
