# Identity

Four layers. Only one of them is identity.

| layer | example | changes? | who depends on it |
| --- | --- | --- | --- |
| **`id`** | `engineering-frontend-developer` | **never** | everything downstream |
| path | `engineering/engineering-frontend-developer.md` | may change | filesystem |
| `name` | `Frontend Developer` | may change | humans, display |
| legacy slugs | stem + name-slug | frozen, derived | 16 tools, runbooks, README |

## Why a third identifier was necessary

The repository already had two identity namespaces, both load-bearing, and they
**disagree for 198 of 270 agents (73%)**:

- **filename stem** — `engineering-frontend-developer`. Used by
  `install_claude_code` and `install_copilot` as the destination filename, by
  `strategy/runbooks.json` rosters, and by every README link.
- **name-slug** — `frontend-developer`, from `slugify(frontmatter.name)`. Used by
  all 14 converters, the Hermes index, and `install.sh --agent`.

Both move under ordinary edits:

- rename the **file** → `runbooks.json` rosters break (caught by CI) and every
  README link breaks (not caught);
- change **`name:`** → the output filename changes for 13 of 16 tools, and
  whatever was previously installed is orphaned, because `install.sh` never
  removes anything.

Neither had a uniqueness check. `build-hermes-plugin.py` guards name-slugs, but
only for its own build and only when that build runs. Zero collisions today was
review discipline, not enforcement.

Nothing downstream — versions, evaluation results, deprecation, aliases,
rollback — can key to something that moves. Hence `id`.

## Why the id looks the way it does

`id` is seeded from the **filename stem, verbatim** (decision D2).

`strategy/runbooks.json` already keys on the stem, so seeding this way cost zero
migration for a live consumer. The cost is cosmetic: stems are not uniformly
division-prefixed, so **70 of 270 ids do not start with their division** —
`game-development/unity/unity-architect.md` has the id `unity-architect`, and
`specialized/agents-orchestrator.md` has `agents-orchestrator`.

That inconsistency is accepted deliberately. Compatibility with a working
consumer is worth more than uniformity of form, and because `id` is decoupled
from path going forward, the inconsistency cannot grow: a new agent's id is
chosen once and never recomputed from where the file happens to sit.

**The seeding rule is not the identity rule.** `id` equals the stem *today*
because that is where it came from. A future move or rename must carry the id
unchanged — `check-identity.py` fails if it does not.

## What is enforced

`scripts/check-identity.py`, run in CI on every PR and push:

1. every agent has an `id` matching `^[a-z0-9]+(-[a-z0-9]+)*$`;
2. ids are globally unique;
3. **immutability** — an id present in the merge base is unchanged. A file that
   disappears while its id lives on is also an error: an id must outlive a move,
   so carry it to the new path rather than dropping it;
4. both legacy namespaces stay unique, and no stem collides with a different
   agent's name-slug.

Points 2 and 4 were previously assumed. Point 3 is the one that matters — an id
that can change is not an identity, and everything keyed to the old value
detaches silently.

## The migration

`scripts/migrate/add_id.py` inserted one line into all 270 files.

It is **surgical text manipulation, not a YAML round trip**. Re-emitting
frontmatter through a dumper would have reordered keys, changed quoting and
normalised unicode across every file — turning a one-line addition into 270
uncontrolled rewrites. Instead a single line is inserted after the opening
fence and every other byte is left alone.

Verified: `git diff --numstat` reports **exactly +1/-0 for all 270 files**, and a
byte-level check confirms each file equals its predecessor with one line
inserted at position 2. The migration is idempotent and refuses to write if any
id would be duplicated.

**The distribution layer is unaffected.** The converters read named fields via
`get_field` and ignore unknown ones, so generated output is byte-identical —
proven against `metrics/conversion-manifest.json`, not assumed.

## Rules

- **Never change an existing `id`.** Not on rename, not on move, not on a
  display-name change.
- **Never rename a file** without understanding that `runbooks.json` and README
  links key on the stem.
- **Never change `name:`** casually — it re-homes generated files for 13 of 16
  tools.
- A **new** agent picks its id once. Convention: match the filename stem at
  creation, so the two agree at birth even though they may diverge later.
- To retire an agent, mark it deprecated in the registry (Phase 4). Do not
  delete the id — references to it must keep resolving.
