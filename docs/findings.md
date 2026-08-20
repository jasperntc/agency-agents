# What was measured, and what it showed

This fork exists to answer one question about the 270 agent files: **do they
work?** Not "do they read well" — do they change outcomes.

That question is now answered on three axes, with blind controls, and the answer
is not the one the corpus was built on. This page is the summary. Each section
links to the full account, including the parts that went wrong.

> The governing principle, from the project handoff: *a skill is not good
> because it is detailed, long, sophisticated-looking, or praised by an LLM. A
> skill is good because controlled evidence shows that it produces better
> outcomes.* **Evidence beats confidence.**

---

## The headline

| axis | what it asks | verdict |
|---|---|---|
| **Selection** | does a model pick the right specialist? | **yes** — 98.28% on 58 blind cases |
| **Diagnosis** | does the agent file help find a defect? | **no measurable effect** — 72 blind subagents, two model tiers |
| **Construction** | does the agent file help write the code? | **inconclusive** — 36 blind subagents, both models at ceiling |

**The frontmatter earns its place. The body has not yet been shown to.**

---

## Selection — the part that works

[selection-evaluation.md](selection-evaluation.md)

58 blind cases, one model, no access to the answer. **98.28% accuracy.**

The figure worth keeping is not the accuracy, which is a ceiling and should be
read as one. It is **literal reachability: 70.18%**. Only about two thirds of
realistic tasks share even one word with the correct specialist's index line.
The other third are reachable only if the request is first translated into the
field's own vocabulary — *"second pair of eyes on this pull request"* →
`code review`.

That is why the router teaches translation explicitly rather than assuming
keyword overlap, and it is the single most load-bearing measurement in the
project.

---

## The Sonnet arm: suggestive, and smaller than it first looked

Every null above was measured on `claude-opus-5`, and the obvious objection —
that the base model is simply strong enough not to need help — was stated as
untested. It has now been tested on **27 blind Sonnet subagents**: all the cases
literal search cannot reach, where a correct pick *requires* translating the
request into the field's vocabulary, plus **8 reachable controls** so a miss can
be attributed to translation rather than to the model being weaker everywhere.

| | `claude-opus-5` | `claude-sonnet-5` |
|---|---:|---:|
| reachable (control) | — | **8/8 (100%)** |
| unreachable (needs translation) | **17/17 (100%)** | **15/17 (88.24%)** |

**The control is perfect and every miss is an unreachable case.** That part is
clean: Sonnet matches Opus wherever the description shares a word with the task.

### The audit cut the effect roughly in half, including against my own reading

First reported as 15/19 against 19/19 — a 21-point gap. Auditing each miss
against the agent's own file rather than its expectation label changed two of
them, and the corrected gap is **two cases**, both arguable:

| case | what happened | verdict |
|---|---|---|
| c038 stormwater | Sonnet declined; Opus picked a structural engineer | **Sonnet was right.** No agent in the corpus sizes drainage. The benchmark was scoring the wrong answer as correct — see below. |
| c050 weekly summary | Sonnet declined | **real description gap**, now fixed. The pick predates the fix, so the run's cross-tab is marked advisory until re-run. |
| c044 decks and fonts | picked `design-ui-designer` over `design-brand-guardian` | defensible; the task says *decks*, which is brand territory, but it is a judgement call |
| c046 manual copying | picked `automation-governance-architect` over `testing-workflow-optimizer` | **corpus overlap**, not a routing failure — two agents claim the same job |

So the honest statement is: **suggestive, not conclusive.** One sample per cell,
and the surviving difference is two cases where the "wrong" pick is defensible.
It is consistent with reachability mattering more for weaker models, and it is
nowhere near enough to prove it.

### The benchmark punished the behaviour the skill instructs

Scoring was `correct = chosen in case["expect"]`, so declining could never be
correct — while SKILL.md tells the model *"if nothing matches well, say so"* and
*"a poorly fitting specialist is worse than none."*

On c038 Sonnet declined and was marked wrong. Opus searched twelve times,
settled on a structural engineer who cannot size stormwater drainage, and was
marked right. **The weaker model gave the better answer and lost for it.**

An empty `expect` now means the corpus has no fit and declining is correct.
Opus's headline drops from 58/58 to 57/58 as a result. A benchmark corrected
until every failure disappears has stopped measuring; this correction runs the
other way.

### What it does and does not say

It says the **description** carries value that varies with model strength, and
that the instrument to find gaps is free.

It does **not** say the agent files improve answers on Sonnet. Nothing here
compares *with agent* against *without agent* — that is the diagnosis and
construction work below. Construction has since been re-run on Sonnet and found
the same ceiling, so the question is still open: whether the corpus helps a
weaker model **produce better work** remains untested, because no task in the
set is hard enough to separate the conditions.

---

## Diagnosis — no effect, with headroom

[behaviour-evaluation.md](behaviour-evaluation.md)

**36 blind subagents, 12 tasks, 40 planted defects, three tiers, three
conditions.**

| tier | `none` | `current` | `flattened` |
|---|---:|---:|---:|
| easy | 11/12 | 11/12 | 11/12 |
| hard | 11/13 | 11/13 | 11/13 |
| niche | 15/15 | 15/15 | 15/15 |

Not just equal totals — on the hard tier, the **same defects found and missed,
task by task**. The niche tier deliberately chose domains where the base model
should be thinner: PostGIS spatial units, Cortex-M0+ firmware, Solidity,
clinical trial methodology. **The no-agent control scored 100%.**

This axis had genuine headroom — three defects went unfound by everyone — and
the agent file did not recover a single one of them.

### The Sonnet arm: the first non-zero lift, pointing the wrong way

36 more blind subagents on `claude-sonnet-5`, all twelve tasks, and the first
behaviour run whose blindness is structural rather than observed.

| condition | recall | vs `none` |
|---|---:|---:|
| `none` | **37/40 (92.5%)** | — |
| `current` | 35/40 (87.5%) | **-5.0** |
| `flattened` | 35/40 (87.5%) | **-5.0** |

**Sonnet's no-agent control equals Opus's**, 37/40 against 37/40. The standing
hypothesis — that a weaker model is where the corpus should show its value —
has now failed on both axes it was tested on.

The negative lift is smaller than it looks and was audited before being
written down. Of the four extra misses, one (`timing_unsafe_compare`) was
missed by **all three Opus conditions** too, so the control finding it is the
outlier; one is `flattened` simply reporting fewer findings. What remains is a
single defect that **both** agent conditions missed and the control caught —
and since `flattened` is a generic file with the body stripped, any effect
there tracks *having a file to read*, not the file's content. One sample per
cell, two defects out of forty: **not evidence that agent files make diagnosis
worse**, and reported only because a number that moves gets reported whichever
way it points.

Two defects are missed by all six condition-arms across both models —
`isinstance(True, int)` passing an integer guard, and wall-clock time used for
an elapsed budget. That is the shape of thing the corpus would have to unlock
to demonstrate value here.

---

## Construction — the tasks are too easy to measure with

[construction-evaluation.md](construction-evaluation.md)

**36 blind subagents, 6 tasks, two models, 288 executed acceptance checks.**

| condition | Opus stated | Opus implied | Sonnet stated | Sonnet implied |
|---|---:|---:|---:|---:|
| `none` | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) |
| `current` | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) |
| `flattened` | 24/24 (100%) | 24/24 (100%) | 24/24 (100%) | 22/24 (91.67%) |

Checks split into `stated` (the brief says it — the floor) and `implied` (a
practitioner meets it unasked — the discriminator). A deliberately naive draft
clears the floor 24/24 and **fails 13 of 24 implied checks**, so the ceiling is
not a cheap one. Both models, with no agent file, independently produced
symmetric integer money arithmetic, keyset cursors stable under insertion,
idempotent merges, HMAC under a derived key, the Slavic teen exception, and a
signature covering the token expiry.

### What the Sonnet arm was for, and what it actually settled

The Opus arm scored 24/24 in every cell including `none`. With the control
already at ceiling there was no headroom, so its **+0.0 lift is uninformative** —
it cannot distinguish *"the agent file adds nothing"* from *"nothing was left to
add."* The Sonnet arm was run to find that headroom: a weaker model, the
prediction went, would drop below ceiling on `implied` without an agent file,
and the comparison would finally carry information.

**It did not drop.** `claude-sonnet-5` with no agent file scored 24/24 stated
and **24/24 implied** — the same ceiling as Opus, on the same tasks.

So the finding is not "agent files don't help." It is narrower and it is about
the instrument:

> **These six tasks are too easy for frontier models.** Two model tiers clear
> every implied check with no agent file at all. Until a construction task
> exists that a bare frontier model fails, this axis cannot measure an agent
> file's contribution in either direction.

The `current`-vs-`none` lift is **+0.0 on both arms**, and on both arms that
number is a ceiling artefact rather than evidence.

### The one cell that moved, audited before reporting

`flattened` c001 (proration) scored 6/8, the only non-ceiling cell in 36
subagents. It is **not** evidence that a generic agent file degrades output, and
the audit is why:

- Both failures are **one root cause**. The answer treated `period_end` as an
  *inclusive* last billed day (`total_days = (end - start).days + 1`); the suite
  assumes the *exclusive* convention. The brief pins only the period **start**
  behaviour and never says which.
- `i_period_end_is_zero` fails because under the inclusive reading one day of
  the new plan remains on the last day, so it charges 65 cents rather than 0.
- `i_symmetric_rounding` fails on its **secondary** assertion — distance from
  exact, which the convention shifts by up to 30.7 cents. The property the check
  is named for holds: the module's round-half-away-from-zero **is** symmetric in
  both directions, verified by hand across all 30 days.

One artifact, one ambiguous convention, two checks keying off it. Reported
because it is the only movement in the matrix, not because it supports anything.

**Limit, stated rather than buried:** with `none` at ceiling on both arms, this
axis currently has no discriminating power at all. That is a fact about the
tasks, not about the corpus.

### The attempt to fix it, which also ceilinged

A seventh task (**c007**, renewal-date anchoring) was built specifically to
have no *named* best practice to recall — the diagnosis being that every
implied check in c001-c006 has a name, and frontier models recall names well.
Eight blind probes on `none`, four per model tier, scored **32/32 implied**
with the reference at 8/8 and the naive draft at 6/8 through the same scoring
path, so the checks were live and the answers were simply right.

That makes **44 blind construction subagents across two model tiers, and
`none` has never once dropped below ceiling.** Three task designs have now
failed to find headroom in the single-module-from-a-brief format, which is
increasingly evidence about the format rather than about any one task.

---

## What is NOT claimed

- Not that the corpus is worthless. Selection works, and works well.
- Not that agent files never help. Two task types, one sample per cell, ten
  agents out of 270. Both axes now carry an Opus and a Sonnet arm, and every
  run records its own `model` field.
- Not that the construction result is a null at all. It is **inconclusive**:
  `none` sits at ceiling on both model tiers, so the comparison has no
  discriminating power. The most likely explanation remains that the base model
  already operates at specialist level on these tasks — and the Sonnet arm,
  which was run to break that ceiling, did not break it.

The honest summary: **on this evidence the router is the valuable artifact, and
the 270 files are a routing surface more than a quality intervention.**

---

## How the instruments were kept honest

Four separate times, the measuring apparatus was wrong and said something
flattering or catastrophic before being corrected.

- **Oracle v1** scored the generic control **25 points above** the real agent.
  Same diagnosis, different words. Replaced rather than widened — widening a
  phrase list to fit collected answers is fitting the key to the data.
- **Oracle v2** produced *exactly the expected ordering*, and every point of it
  was a scoring artefact. A run that confirms the hypothesis is the least likely
  to be audited, which makes it the most dangerous kind of wrong.
- **Four construction suites** punished correct answers. The worst used a
  six-character salt that all three conditions refused — correctly — scoring
  every one of them 0/8.
- **Five separate CI checks** have been green in this repository while measuring
  nothing at all.
- **The diagnosis question file *was* its own answer key.** All 40 planted
  defects — ids, exact line ranges, descriptions — sat in the same record as
  the prompt in `eval/behaviour/tasks.jsonl`, while scoring is *cite the line
  number*. The guard checked the rendered prompt, which is a narrower question
  than the one that mattered: what an answerer can reach, not what it was
  handed. Question and key are now separate files, the key is withheld during a
  run, and three tests enforce it. The recorded runs scored 37/40 with three
  defects missed by every condition, which is not what exploitation looks like
  — but the door was unlocked.
- **The construction question file leaked its own answer key.** Every task
  carried a `why` field in `tasks.jsonl` naming the discriminator — c002's said
  offset paging *"breaks the moment a row is inserted"* — while the blindness
  guard inspected only the `brief`. Both committed arms were collected with it
  open. `why` now lives in the withheld suite; the arms' blindness is
  correspondingly weakened and
  [said so plainly](construction-evaluation.md) rather than restated.

The standing defences, all enforced in CI:

1. **Two controls, always.** `none` (no agent file) and `flattened` (a generic
   agent file, real frontmatter, body stripped). Without the second you cannot
   tell whether the instrument sees skill *quality* or merely skill *presence*.
2. **Two-sided calibration.** A competent reference must pass every check; a
   deliberately naive draft must clear the floor and **fail at least one
   discriminating check per task**, or that task cannot separate anything.
3. **The digest binds to the question, never the answer key.** Correcting an
   oracle re-scores committed answers for free. This paid off four times.
4. **No aggregate hides a per-dimension result.**

---

## What IS being built, and why it points at descriptions

[proposals.md](proposals.md)

The one improvement loop the evidence supports. Bodies have been measured on two
model tiers across two axes and have never moved a number upward; descriptions
sit on the axis that works and still has **~30% of realistic tasks unreachable
by literal search**. So corrections observed in real work become proposed
description changes, and each is scored — free, deterministically, no model —
on whether it reaches a case it could not reach before **without starting to
compete for cases it is not the answer to**.

The gate's first version accepted both keyword-stuffed calibration proposals,
because it counted phrase collisions and stuffing single words creates none. The
corrected measure rejects them — and rejects **two of the three real proposals
too**:

| proposal | wins | competes for | verdict |
|---|---:|---:|---|
| add "pull request review" to the code reviewer | 1 | 1 | **ACCEPT** |
| add load/concurrent/response-time to the benchmarker | 1 | 2 | REJECT |
| add weekly-sync/standup to the meeting-notes agent | 1 | 4 | REJECT |

That is the finding, not an inconvenience: **widening a description to reach one
more task usually costs more than one task in new competition.** Reaching your
own test case is easy; not trampling 269 neighbours is the work. Nothing in the
loop edits an agent file — it scores, and a person applies.

---

## What is not being built, and why

Three planned phases were cancelled on evidence rather than fatigue.

| phase | decision | reason |
|---|---|---|
| **9 — Learning + proposals** | cancelled | It exists to propose skill improvements. Two nulls mean improvement is not currently measurable at this granularity, and Anthropic's `skill-creator` covers per-skill iteration. |
| **10 — External skill intake** | cancelled | Quarantine and security controls already shipped in Phase 5. The behavioural-comparison half is `skill-creator`'s job. |
| **11 — Public trust** | cancelled | Decision D7 settled distribution as local/personal. This phase was always contingent on going public. |

Anthropic's [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)
now ships a `without_skill` baseline, blind comparators, and description tuning
that measures trigger hit rate. That is the per-skill evaluation loop, and it
should be used instead of rebuilding one here.

What it does **not** cover, and what this repository still uniquely provides:
tuning a description so it wins against **269 competitors** rather than merely
triggering on its own prompts.

---

## Consumption, and one constraint worth remembering

See [consuming.md](consuming.md) for the full setup. The short version:

| setup | context cost | delegation |
|---|---:|---|
| `router@agency` — **the default** | ~1,100 tokens | no, the specialist is read inline |
| one division, e.g. `engineering@agency` | ~3,800 tokens | yes, real subagents |
| all 17 divisions | ~17,900 tokens | yes |

**Do not convert the 270 into Skills.** Claude Code loads skill descriptions
into a listing budgeted at ~1% of the context window, and
[when that listing overflows it truncates descriptions and then drops them
entirely](https://code.claude.com/docs/en/skills), starting with the least-used
entries. At 270 agents the listing would exceed its budget many times over, and
routing would degrade silently — on exactly the specialists you reach for least.

The router avoids this by construction: 270 descriptions never enter context at
all. It greps a 79KB index and loads only the match.
