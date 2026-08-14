# Corpus metrics

Measurement layer for the skill engineering system. Everything here is
**additive**: it reads the agent corpus and writes only to `metrics/`. No
distribution script (`convert.sh`, `install.sh`, `lib.sh`) is modified, and no
new dependency is introduced on the install path.

## Why this exists

Structural validation answers "is the file well-formed?". It cannot answer
"did this change make the library better or worse?". These tools produce the
evidence needed for the second question.

The first artifact is a frozen baseline. Every later claim — *this change is
byte-neutral*, *the corpus grew N%*, *this agent regressed* — is meaningless
without a fixed reference to compare against.

## Tools

### `scripts/inventory.py`

Deterministic per-agent inventory: path, division, filename stem, display name,
name-derived slug, sha256 of raw bytes, byte count, body word count.

```bash
# Snapshot a git ref (no checkout required)
./scripts/inventory.py --ref upstream-baseline-2026-08-13 --out metrics/inventory-baseline.json

# Verify the working tree still matches the baseline
./scripts/inventory.py --check metrics/inventory-baseline.json

# Snapshot the working tree to stdout
./scripts/inventory.py
```

`--ref` streams blobs through `git cat-file --batch`, so any ref can be measured
without touching the working tree — including branches such as
`archive/fable-upgrade`.

## Baseline

`metrics/inventory-baseline.json`, taken at tag `upstream-baseline-2026-08-13`
(the fork point, byte-identical to upstream `main`).

| Measure | Value |
| --- | --- |
| Agents | 270 |
| Divisions | 17 |
| Total body words | 502,635 |
| Duplicate filename stems | 0 |
| Duplicate name-slugs | 0 |
| Stem ≠ name-slug | 198 (73%) |
| Slug-implementation divergences | 0 |

Per division: engineering 58, specialized 57, marketing 36, game-development 21,
gis 13, security 12, design 10, sales 9, testing 9, paid-media 7,
project-management 7, academic 6, spatial-computing 6, support 6, finance 5,
product 5, healthcare 3.

### Reading the identity numbers

The repository carries two identity namespaces, both load-bearing:

- **filename stem** (`engineering-frontend-developer`) — used by
  `install_claude_code` / `install_copilot` destination names, by
  `strategy/runbooks.json` rosters, and by every README link.
- **name-slug** (`frontend-developer`, from `slugify(frontmatter.name)`) — used
  by all 14 converters, by the Hermes index, and by `install.sh --agent`.

They disagree for 198 of 270 agents. Both are currently collision-free, but
**nothing in CI enforces that** — only `build-hermes-plugin.py` checks
uniqueness, and only for the second namespace, and only when that build runs.
The inventory surfaces `duplicate_filename_stems`, `duplicate_name_slugs`, and
`stem_slug_mismatches` so the invariant is measured rather than assumed. Phase 3
replaces the assumption with an enforced immutable `id`.

`slug_implementation_divergences` compares the repo's **two** slug
implementations — `scripts/lib.sh slugify` (byte-wise `tr`/`sed`) and
`scripts/build-hermes-plugin.py slugify` (Unicode-aware `re`). They agree on the
current corpus. They would diverge on a non-ASCII display name, which matters if
localized agent names are ever adopted.

## Parsing fidelity — deliberate, do not "fix"

`inventory.py` reproduces the **current** toolchain's frontmatter semantics
(`scripts/lib.sh`) exactly, including its known defects:

- one line only, so a continued multi-line value is truncated;
- extra alignment whitespace after `field: ` is preserved in the value;
- quotes are not stripped;
- body lines equal to `---` are dropped.

This is intentional. The inventory must record **what the distribution layer
actually sees today**, not what a correct YAML parser would see. Phase 2
introduces the authoritative parser (`scripts/lib/frontmatter.py`) and reports
the divergence between the two as a first-class finding. Making this file
"correct" early would silently erase that finding.

## Determinism rules

Every tool here must satisfy:

- stdlib only, no install-path dependencies;
- output sorted, `sort_keys=True`, no timestamps, no host/user/env data;
- **LF newlines written as bytes** — Python text mode emits CRLF on Windows,
  which would make identical input produce different bytes per platform. That
  is exactly the class of bug this project exists to catch;
- two consecutive runs are byte-identical.

## Windows note

`C:\Python312` ships no `python3.exe`, so bare `python3` hits the Microsoft
Store alias and fails. A shim at `~/bin/python3` (PATH position 1 in Git Bash)
forwards to the real interpreter. Required by `check-runbooks.sh`,
`check-agent-originality.sh`, `convert.sh --tool hermes`, and
`install.sh --tool hermes`.
