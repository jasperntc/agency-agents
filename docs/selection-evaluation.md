# Selection evaluation

[routing-evaluation.md](routing-evaluation.md) measures whether the right
specialist can be **found** by literal search. This measures whether a model
**picks** it — including on the third of tasks that literal search cannot reach
at all.

```bash
./scripts/eval_selection.py                 # score every recorded run
./scripts/eval_selection.py --check         # CI: fail if the baseline is stale
./scripts/eval_selection.py --sample 15     # the deterministic pilot subset
./scripts/eval_selection.py --prompt c041   # the blind prompt for one case
```

## The cross-tab is the point

An accuracy number on its own blends four different outcomes. Crossed with Phase
6's reachability, they separate:

| | picked right | picked wrong |
| --- | --- | --- |
| **literally reachable** | routing works | judgment failure — it was in the results and the model chose badly |
| **not reachable** | **translation worked** | compound failure |

The top-right cell is a prompt problem; the bottom-left is the one that matters.
Those cases share no word with the right agent's index line, so a correct pick
means the model turned "second pair of eyes on this pull request" into
`code review` before searching — the thing the router skill was rewritten to
teach in Phase 6, and the thing the deterministic harness cannot see even in
principle.

A fifth outcome is tracked separately: the model may answer `NONE`. That is
scored as a decline, not a wrong pick, because the skill explicitly tells it a
poor match is worse than none — punishing honesty would train exactly the
behaviour the skill warns against.

## Why the picks are committed input

Scoring is a pure function of `(cases, responses)`. No model is called by the
scoring script. That is what lets `--check` run in CI at all: a script that
called a model would be nondeterministic, would need a key, and could not be
verified.

So a run happens once, records its picks into
`eval/selection/responses/<name>.json`, and is reproducible forever after. It
also makes the two runners interchangeable:

| runner | cost | automated |
| --- | --- | --- |
| **subagent** — blind agents in a Claude Code session | none beyond existing usage | no |
| **api** — a key and the Messages API | ~$1.30 per 58-case run on Claude Opus 5 | yes |

Both produce the same artifact and are scored by the same code, so starting on
the free path does not fork the measurement. **Decision D5 is therefore settled
as: no CI spend for now.** The switch is a secret and a cron whenever that
changes.

## Blindness, and why it needed engineering

The obvious way to run this — ask the assistant that wrote the benchmark to
answer it — is worthless. `cases.jsonl` carries the expected agent on every
line, and the author of the cases is also the author of the skill under test.

So each case is answered by a **subagent with a clean context**. It receives the
task text, the shipped `SKILL.md`, and the index; it never receives `expect`,
`why`, or `kind`. `--prompt <case>` generates exactly that, and the prompt
deliberately contains **no routing advice** — any hint added there would measure
the prompt rather than the skill consumers actually get.

Two mechanical guards back this up:

- Every responses file records a **sha256 of `cases.jsonl`**, and scoring is a
  hard error if it no longer matches. Picks are answers to specific questions;
  scoring them against an edited benchmark changes the number with no other
  visible sign.
- `--sample N` is **deterministic and stratified** — round-robin across the
  divisions of the expected agents, no RNG. The obvious alternative, the first
  N cases, over-weights whichever divisions were authored first, which would
  make a pilot's numbers a property of that accident.

### A limitation to keep in view

A subagent given the skill is not identical to a user's main session with the
plugin enabled: it starts cold, it has a different surrounding system prompt,
and it knows it is being asked to route. It is much closer than a synthetic
harness, and it is the same model, but it is a proxy. Read the results as
evidence about the skill, not as a simulation of the product.

## Pilot before the full run

The first run of any new instrument here has twice been wrong in a way that
looked like a result:

- `eval_routing.py` reported **271 agents** — the index's own header line parsed
  as an entry.
- `test_check_promotion.py` **passed locally and ran vacuously in CI** — an
  unresolvable ref returned "nothing changed", so the Fable detector asserted
  against an empty set and reported success.

So a selection run starts with `--sample 15`, whose numbers are an **instrument
check, not a result**. It happens to be a strong subset: 15 cases across 15
distinct divisions, 7 of them cases Phase 6 marks unreachable. It does not
include the two `adversarial` cases — those land in the full run, and the pilot
should not be read as covering them.

## What the first pilot found (2026-08-15)

Fifteen blind subagents, one per case, `claude-opus-5`. Recorded in
`eval/selection/responses/2026-08-15-subagent-pilot15.json`.

**The instrument works.** Blindness held, every pick was attributable to a case,
and the cross-tab populated as designed. Two defects surfaced, both in the
harness rather than the router:

- **The output contract is not reliably held.** Two of fifteen subagents (c004,
  c042) prepended a paragraph of justification despite "Reply with exactly two
  lines and nothing else." A recorder that assumed line 1 was the answer would
  have silently mis-read both. Picks are extracted by pattern, not position. The
  prompt was deliberately **not** changed — editing it mid-run would break
  comparability with the remaining cases.
- **`--sample N` makes a small sample structurally easy.** Round-robin assigns
  at most one case per division before revisiting any, so a 15-case sample lands
  one case in each of 15 divisions and never makes two cases compete inside the
  same one. Measured: **52 of the 58 full-set cases sit in a division with at
  least one competing case; 0 of the pilot's 15 do.** Engineering carries 17
  cases in the full set and 1 in the pilot.

That second finding is the one that matters, because it means **the pilot's
accuracy figure is not an estimate of the full set's.** Within-division
discrimination — choosing one of 58 engineering specialists — is the harder half
of routing, and the pilot barely exercises it. It also contains neither
`adversarial` case. `sample()` now documents this bias in its own docstring.

**The one result worth keeping** is the translation cell. All 7 pilot cases that
Phase 6 marks literally unreachable were answered correctly, and the recorded
queries show why — every one searched a term that does not appear in the task:

| case | task never says | model searched |
| --- | --- | --- |
| c007 | tax | `tax` |
| c022 | discovery | `discovery call` |
| c042 | meeting, decision | `meeting`, `decision log\|action item` |
| c002 | app store | `app store` |
| c013 | feedback, sentiment | `feedback`, `sentiment` |

That is direct evidence for the instruction added to the router skill in Phase
6, on exactly the cases Phase 6 could not measure. It is a small sample and an
easy one, but the mechanism is visible in the queries rather than inferred from
the score.

**Effort varies more than correctness does.** Median 6 tool calls per pick,
range 4&ndash;17. `c050` spent 17 calls and 13 distinct query patterns before
landing; `c022` needed 5 and 2. Both score identically. Cost is now recorded per
pick precisely because the correct/wrong axis hides it.

## What this does not measure

- **Whether the answer helps.** A correct pick is scored correct; nothing here
  judges whether adopting that specialist improved the eventual work.
- **Multi-agent tasks.** One pick per case, even where two specialists would
  legitimately both apply. Cases with genuine overlap list alternates in
  `expect` and any of them scores correct.
- **Variance.** One sample per case per run. Two runs of the same model will
  differ, and a single run's accuracy should not be quoted to the decimal.
  Recording several runs is the intended way to see the spread — hence one file
  per run, rather than one file that gets overwritten.
