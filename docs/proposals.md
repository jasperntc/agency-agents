# Proposing a description change, and proving it helps

This is the improvement loop the project kept, and the reasoning for why it is
pointed where it is.

## Why descriptions and not bodies

Three axes, each now measured on two model tiers:

| axis | subagents | result |
|---|---:|---|
| **selection** | 58 blind cases | **works** — 57/58, literal reachability **70.18%** |
| diagnosis | 72 | no measurable effect; `none` scores the same on Opus and Sonnet |
| construction | 44 | at ceiling on both tiers; `none` has never dropped below 100% implied |

A loop proposing improvements to agent **bodies** would be optimising against
instruments that have never detected anything. A loop proposing improvements to
**descriptions** is optimising against the one instrument here that works, on
the one axis with measured headroom — the ~30% of realistic tasks that share no
word with the right agent's index line.

If that evidence ever changes, this loop should be pointed somewhere else. It
is a consequence of the measurements, not a preference.

## The shape of the loop

    observe  ->  propose  ->  score  ->  a human applies it

    observe   Something went wrong while actually working: the router picked
              the wrong specialist, or needed steering, or declined when it
              should not have. Or eval_routing reports a case as literally
              unreachable. Either way it goes in the log as an observation,
              not a fix.

    propose   One agent, one replacement description, recorded with what
              prompted it, in eval/proposals/descriptions.jsonl.

    score     ./scripts/propose_descriptions.py. Free, deterministic, no model.

    apply     A person edits the frontmatter and commits. Nothing in this loop
              writes to an agent file.

That last separation is deliberate. An automatic rewriter produces unproven
content faster, which is the exact failure this repository exists to avoid — a
count of "improvements applied" is not evidence of improvement.

## The gate

    gained      target cases going UNREACHABLE -> REACHABLE. The point.
    lost        any case, anywhere, that was reachable and no longer is.
    attracted   other cases — ones this agent is not the answer to — whose task
                now reaches it when it did not before.

    ACCEPT iff gained > 0 and lost == 0 and len(attracted) <= len(gained)

The exchange rule is plain on purpose: a description may start competing for at
most as many cases as it wins. No tuned threshold, because tuning a threshold
is how a gate gets fitted to the proposals it is supposed to judge.

### The gate failed its own calibration first

The first version counted adjacent **phrase** collisions only, reasoning that
phrases are what a person would really grep for. Both keyword-stuffed
calibration proposals sailed through it: stuffing single topic words creates no
adjacent-phrase collisions, so the measure was blind to the precise failure it
existed to catch. Counting distinct **cases** reached — singles and phrases
alike — sees it.

| proposal | wins | starts competing for | verdict |
|---|---:|---:|---|
| `p001` code-reviewer, adds "pull request review" | 1 | 1 | **ACCEPT** |
| `p002` performance-benchmarker, adds load/concurrent/response time | 1 | 2 | REJECT |
| `p003` meeting-notes, adds weekly sync/standup | 1 | 4 | REJECT |
| `g001` calibration, keyword-stuffed reviewer | 1 | 7 | REJECT |
| `g002` calibration, keyword-stuffed recruiter | 1 | 6 | REJECT |

**Two of the three real proposals fail.** That is the gate working rather than
the proposals being carelessly written, and it is the substantive finding:
widening a description to reach one more task usually costs more than one task
in new competition. Reaching your own test case is easy; not trampling 269
neighbours is the hard part, and it is the part a plausible-sounding rewrite
silently skips.

### What the gate does not prove

Appearing in a candidate set is not the same as being picked. Selection sits at
57/58, so the router discriminates well among candidates, and `attracted`
therefore overstates real harm by some unknown amount. It is a proxy for
competitive pressure — deterministic and free, which is why it can run on every
push. **A proposal it rejects is not proven harmful, only unproven.** Anyone who
wants a rejected proposal anyway should say so in the commit and re-run
`eval_selection.py` afterwards, which is the measure that actually counts picks.

## Recording an observation

Append one line to `eval/proposals/descriptions.jsonl`:

```json
{"id": "p004", "agent": "engineering-sre", "targets": ["c014"],
 "source": "measured-gap",
 "observed": "c014 asks for 'proper alerting and an agreed tolerance for downtime'. The description says SLOs and error budgets, which is the same idea in the field's own vocabulary and shares no word with the request.",
 "proposed": "...", "recorded_at": "2026-08-21"}
```

`source` is `measured-gap` (eval_routing says the case is unreachable) or
`session-correction` (it went wrong in real work). `observed` records what
prompted it — a proposal with no observation behind it is a guess, and the
schema test rejects it.

A proposal may change **a description and nothing else**. The 270 filename
stems, ids and `name` values are load-bearing identity; a proposals file
carrying any of those fields fails the schema test as a category error.

## Commands

```bash
python scripts/propose_descriptions.py
```

```bash
python scripts/propose_descriptions.py --calibrate
```

```bash
python scripts/propose_descriptions.py --show p001
```
