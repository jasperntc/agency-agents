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
| **Selection** | does a model pick the right specialist? | **yes** — 100% on 58 blind cases |
| **Diagnosis** | does the agent file help find a defect? | **no measurable effect** — 36 blind subagents |
| **Construction** | does the agent file help write the code? | **no measurable effect** — 18 blind subagents |

**The frontmatter earns its place. The body has not yet been shown to.**

---

## Selection — the part that works

[selection-evaluation.md](selection-evaluation.md)

58 blind cases, one model, no access to the answer. **100% accuracy.**

The figure worth keeping is not the accuracy, which is a ceiling and should be
read as one. It is **literal reachability: 67.24%**. Only about two thirds of
realistic tasks share even one word with the correct specialist's index line.
The other third are reachable only if the request is first translated into the
field's own vocabulary — *"second pair of eyes on this pull request"* →
`code review`.

That is why the router teaches translation explicitly rather than assuming
keyword overlap, and it is the single most load-bearing measurement in the
project.

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

---

## Construction — no effect, at ceiling

[construction-evaluation.md](construction-evaluation.md)

**18 blind subagents, 6 tasks, 144 executed acceptance checks.**

| condition | stated | implied |
|---|---:|---:|
| `none` | 24/24 (100%) | 24/24 (100%) |
| `current` | 24/24 (100%) | 24/24 (100%) |
| `flattened` | 24/24 (100%) | 24/24 (100%) |

Checks split into `stated` (the brief says it — the floor) and `implied` (a
practitioner meets it unasked — the discriminator). A deliberately naive draft
clears the floor 24/24 and **fails 13 of 24 implied checks**, so the ceiling is
not a cheap one. The base model, with no agent file, independently produced
symmetric integer money arithmetic, keyset cursors stable under insertion,
idempotent merges, HMAC under a derived key, the Slavic teen exception, and a
signature covering the token expiry.

**Limit, stated rather than buried:** at 100% there is no headroom, so this
cannot separate *"the agent file adds nothing"* from *"these tasks were too
small to need one."* It does rule out the hypothesis it was built for — the base
model does not write naive code here.

---

## What is NOT claimed

- Not that the corpus is worthless. Selection works, and works well.
- Not that agent files never help. Two task types, one model (`claude-opus-5`
  throughout — every run records its own `model` field), one sample per cell,
  ten agents out of 270.
- Not that the result generalises to weaker models. **It plausibly does not** —
  the most likely explanation of both nulls is that the base model already
  operates at specialist level on these tasks. That is a testable claim and the
  harnesses are built to test it.

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
