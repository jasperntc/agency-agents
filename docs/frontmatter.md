# Frontmatter: the contract and the four parsers

`schema/agent.schema.json` is the machine-readable contract for agent
frontmatter. `scripts/lib/frontmatter.py` is the authoritative parser.

```bash
python3 -m pip install -r requirements-dev.txt

./scripts/check_frontmatter.py     # validate + report divergence and advisories
python3 tests/test_frontmatter.py  # 13 tests against the real corpus
```

## Why a schema, when the linter already checks required fields

`scripts/lint-agents.sh` greps for the presence of `name`, `description` and
`color`. **Presence is not validity.** A value can be present and still be a
multi-line scalar that every converter truncates, or a `services` block no
renderer can read. The linter is the fast structural check; the schema is the
contract. Both run in CI.

Version 1.0.0 is deliberately **descriptive, not aspirational**. It was derived
by parsing all 270 agents with a real YAML parser and writing down what is
actually there, so it could be enforced immediately without changing a single
agent. All 270 validate with zero loosening.

The canonical `id` field arrives in 1.1.0 (Phase 3).

## Four parsers, and they disagree

| reader | used by | kind |
| --- | --- | --- |
| `scripts/lib.sh get_field` | `convert.sh`, `install.sh` | awk, line-based |
| `scripts/build-hermes-plugin.py` | the Hermes plugin | Python, line-based |
| `scripts/i18n/localize-agents-zh.ps1` | zh-CN localisation | PowerShell regex |
| `scripts/lib/frontmatter.py` | this engineering layer | **real YAML** |

None of the first three is a YAML parser. They read one line per key, do not
strip quotes, and cannot represent a block value.

`compat_get_field` reproduces the first one **exactly**, defects included, so
the disagreement can be measured rather than guessed at. `tests/test_frontmatter.py`
verifies that reimplementation against the actual shell function by sourcing
`lib.sh` and comparing outputs — the divergence report is only trustworthy if
the stand-in is faithful.

## The measured divergence

104 (file, field) pairs, in exactly two classes:

| cause | count | fields |
| --- | ---: | --- |
| quotes not stripped | 100 | `color` ×93, `description` ×3, `emoji` ×3, `vibe` ×1 |
| block value invisible | 4 | `services` ×4 |

There is no `truncated` class any more — Step 0.4a repaired the three agents
that had it — and no unclassified `other`. `test_all_divergence_is_explained`
fails if a new cause appears, because an unaccounted disagreement means the
distribution layer is reading something nobody has reasoned about.

### What the quote divergence cost

`get_field` returns `"#D97706"` — nine characters, quotes included — for a
quoted colour. `resolve_opencode_color` then tested it against `^#[0-9a-fA-F]{6}$`,
which cannot match a leading quote, and fell through to the grey default.

**93 of 270 agents rendered as `#6B7280` in OpenCode instead of the colour they
declare.** Measured against the generated output, not inferred: 93 of 93.

Fixed in `resolve_opencode_color`, **not** in `get_field`. Those quotes are
load-bearing elsewhere: three agents have a description containing `": "`, which
is only valid YAML *because* it is quoted, and the converters re-emit
description verbatim into generated frontmatter. Stripping quotes centrally
would reintroduce the invalid-YAML defect repaired in `121969d`.
`resolve_opencode_color` is the one place a value is *interpreted* rather than
passed through.

## Advisories

Valid per the contract, wrong in practice. Reported, never fatal by default
(`--strict` makes them fatal).

- **`color` ×4** — `slate` (×2) and `navy` (×2) are not names `convert.sh`
  knows, so OpenCode renders them grey. Left as-is deliberately: choosing a hex
  value for "slate" is a design decision, not a correctness fix.
- **`services` ×4** — declared in CONTRIBUTING.md and validated here, but **no
  converter carries it into any of the 14 output formats**, because `get_field`
  cannot read a block value. It is a documented contract with no consumer.

### The `services` decision is still open

Three options, none taken yet:

1. **Carry it** — a renderer reads `services` and emits it. Makes the field real,
   changes generated output for 4 agents.
2. **Drop it** — remove from CONTRIBUTING.md and the schema. Honest, loses
   declared dependency metadata.
3. **Keep as source-only metadata** — explicitly document that it is for humans
   and the registry, never for renderers. Cheapest; the registry (Phase 4) is a
   natural consumer.

Option 3 is the likely answer once the registry exists, but it should be a
decision rather than a drift.

## Scope

This layer may use dependencies (`requirements-dev.txt`). The **distribution
path must not**: `convert.sh`, `install.sh` and `lib.sh` stay bash 3.2 with no
`jq` and no pip, because a user installing agents must never need any of it.

Migrating the converters onto this parser is a separate, deliberate change —
their output is a contract with 16 tools, and 104 divergent pairs means such a
migration would change generated bytes for a large fraction of the corpus. The
manifest (`metrics/conversion-manifest.json`) exists so that change would be
visible rather than silent.
