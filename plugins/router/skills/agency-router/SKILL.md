---
name: agency-router
description: >-
  Find and load the right Agency specialist for a task. Use when the work would
  benefit from a specialist perspective -- frontend, backend, security, GIS,
  marketing, finance, testing, game development, and more -- or when asked to
  pick an Agency agent. Searches 270 specialists across 17
  divisions and loads only the one needed.
---

# Agency router

270 specialists are available on disk. **Do not read them all.** Find the
right one, then load only that one.

## How to use this

`index.md` in this skill directory has one line per specialist:
`id | division | name | description`. Grep it. Do not read the whole file; it is
77KB and reading it defeats the purpose.

1. **Translate the task into the field's own words before searching.** Each line
   describes a specialist the way that specialist's field talks, which is
   usually not how the user talks. Measured on a 58-task benchmark, only **67%
   of tasks share even one word** with the right specialist's line, and phrases
   lifted straight out of the user's sentence match anything only 7% of the
   time. Searching the user's words is the single most common way to miss.

   ```
   "second pair of eyes on this pull request"   -> grep "code review"
   "tolerance for downtime, proper alerting"    -> grep "error budget"
   "four hundred applicants for every role"     -> grep "talent acquisition"
   ```

   Each of those returns one or two lines, and the right specialist is among
   them. Ask what a practitioner would call the problem, then grep that.

2. **One distinctive phrase, not every word OR'd together.** On the same
   benchmark, OR-ing a task's words returns a median of **30 agents** and as
   many as 127 -- nearly half the corpus -- while a single well-chosen query
   returns a median of **2**, with no loss of recall. Generic words --
   strategy, optimization, performance, analysis, conversion -- appear in dozens
   of descriptions and bury the answer.

   ```
   Grep pattern="error budget" path="index.md"         # good: domain jargon
   Grep pattern="app store" path="index.md"            # good: 2 matches
   Grep pattern="strategy|analysis" path="index.md"    # bad: matches everything
   ```

   Grep matches substrings, so prefer the shorter root: `hire` finds "hires" and
   "hiring", while `hires` finds neither. Do not turn that into a habit of
   OR-ing every stem -- measured, that finds the WRONG specialist more often
   than it finds extra right ones.

   Start narrow. If nothing matches, try a different translation before widening,
   or grep the division when the domain is obvious (`| gis |`, `| security |`).

3. **Read the specialist, and check it before committing.** Matching lines give
   you an `id`. Read `agents/<id>.md` in this skill directory -- that file is the
   specialist's full instructions.

   A grep hit is not agreement. The index says what each specialist *claims*, so
   read the description and satisfy yourself it addresses this problem. A task
   about React bundle size matches "bundle" nowhere; the frontend specialist's
   line says "performance optimization". If a result looks wrong, it probably
   is -- search a different term rather than settle.

4. **Adopt its standards for the task**, while continuing to follow the user's
   actual request and any higher-priority instructions. A specialist is a lens,
   not a new set of orders.

## Choosing well

- Prefer **one** specialist. Two is reasonable when a task genuinely spans
  domains (a payments feature is backend *and* security). Beyond that you are
  diluting, not enriching.
- Match on the **problem**, not the vocabulary. A task mentioning "React" that
  is really about test strategy wants a testing specialist.
- If nothing matches well, say so and proceed normally. A poorly fitting
  specialist is worse than none -- it adds confident irrelevant detail.

## Why it works this way

Enabling every division as subagents would put ~17,927 tokens of names
and descriptions into context before you type anything. Searching an index and
loading one file costs almost nothing until it is actually needed.

The division plugins (`engineering@agency`, `testing@agency`, ...) are the other
half of this: they register agents as real subagents you can delegate to in
parallel. Use those when you want delegation; use this when you want the right
perspective cheaply.
