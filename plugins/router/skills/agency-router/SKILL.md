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

1. **Search the index.** `index.md` in this skill directory has one line per
   specialist: `id | division | name | description`. Do not read the whole file;
   it is 77KB and reading it defeats the purpose.

   **Search distinctive phrases, not every word OR'd together.** Measured on
   this index, `app store|listing|conversion` returns 13 mostly irrelevant
   matches, while `app store` returns 2 and both are right. Generic words --
   conversion, optimization, strategy, performance, analysis -- appear in
   dozens of descriptions and drown the signal.

   ```
   Grep pattern="app store" path="index.md"          # good: distinctive
   Grep pattern="post-mortem|on-call" path="index.md" # good: domain jargon
   Grep pattern="strategy|analysis" path="index.md"   # bad: matches everything
   ```

   Start narrow. If nothing matches, widen one term at a time, or grep the
   division name when the domain is obvious (`| gis |`, `| security |`).

2. **Read the specialist.** Matching lines give you an `id`. Read
   `agents/<id>.md` in this skill directory. That file is the specialist's full
   instructions.

   **Check the description before committing to it.** The index describes what
   each specialist *claims*, in its own vocabulary, which may not be the
   vocabulary of the task. A task about React bundle size does not match
   "bundle" anywhere -- the frontend specialist's description says "performance
   optimization". If a grep returns something that looks wrong, it probably is;
   search a different term rather than using a poor match.

3. **Adopt its standards for the task**, while continuing to follow the user's
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

Enabling every division as subagents would put ~17,899 tokens of names
and descriptions into context before you type anything. Searching an index and
loading one file costs almost nothing until it is actually needed.

The division plugins (`engineering@agency`, `testing@agency`, ...) are the other
half of this: they register agents as real subagents you can delegate to in
parallel. Use those when you want delegation; use this when you want the right
perspective cheaply.
