# Conversion determinism

The distribution layer turns 270 agent files into **4,055 generated files across
14 tools**. Before anything measures what those files produce, the same source
must produce the same bytes — on every run, and on every machine.

Otherwise behavioural evaluation measures the build rather than the skill, and
you spend your time chasing eval flake that is really conversion flake.

## The contract

```bash
# regenerate and compare against the recorded hashes
./scripts/conversion_manifest.py --check metrics/conversion-manifest.json

# reuse an already-built tree (convert.sh takes minutes on Windows)
./scripts/conversion_manifest.py --from <dir> --check metrics/conversion-manifest.json

# two full runs, diffed, plus the renderer-equivalence checks
./tests/test-convert-determinism.sh
```

`metrics/conversion-manifest.json` holds a sha256 for every generated file. CI
regenerates and compares on every PR touching an input.

**It is a lockfile, not build output.** It records hashes, not files. The
repository's "generated output is never committed" rule is intact.

Because the manifest is generated on one OS and verified on another, it catches
platform-dependent output as well as run-to-run instability — and it catches
unintended renderer changes, which are often correct but should be deliberate
and visible rather than discovered later by a consumer.

## Three defects this found

### Locale-dependent agent ordering

`find … -print0 | sort -z` decides the order agents are processed. Without a
pinned collation, `sort` follows the caller's locale. Per-agent renderers don't
care — each agent writes its own file — but **aider and windsurf accumulate into
a single roster file, where order *is* content.**

Measured on the real corpus, C and `en_US.UTF-8` disagree:

| C locale | `en_US.UTF-8` |
| --- | --- |
| `code-reviewer` | `codebase-onboarding-engineer` |
| `codebase-onboarding-engineer` | `code-reviewer` |
| `data-engineer` | `database-optimizer` |
| `database-optimizer` | `data-engineer` |

The cause is hyphen collation: in C, `-` (0x2D) sorts before letters, so
`"code-"` precedes `"codeb"`. A UTF-8 locale ignores punctuation at the primary
level, so `"codeb"` precedes `"coder"` and the pair swaps. Most macOS and Linux
machines run a UTF-8 locale, so `CONVENTIONS.md` and `.windsurfrules` genuinely
differed between contributors.

Fixed by `LC_ALL=C sort -z` in `convert.sh`.

### CRLF in the generated Hermes plugin

`build-hermes-plugin.py` used `Path.write_text()` without `newline=`, so text
mode translated `\n` to the platform separator — CRLF on Windows, LF on Linux.

This is the one place the repository generates **executable** content: the
plugin is Python installed into `~/.hermes/plugins/`. Its identity should not
depend on who built it.

| file | CR before | CR after |
| --- | ---: | ---: |
| `data/agents.json` | 2,972 | 0 |
| `__init__.py` | 300 | 0 |
| `README.md` | 79 | 0 |
| `plugin.yaml` | 8 | 0 |

Fixed with `newline="\n"`. The change was verified newline-only two ways: content
is byte-identical once newlines are normalised, and the size delta equals the CR
count exactly. It is a no-op on Linux.

### OS separators in the Hermes plugin data

**Found by CI on the manifest's first run** — and worth dwelling on, because
local testing could not have found it.

`parse_agent` recorded each agent's path with `str(rel)`. `str(PurePath)` uses
the OS separator, so the same source produced:

```
Windows:  "source_path": "academic\\academic-anthropologist.md"
Linux:    "source_path": "academic/academic-anthropologist.md"
```

for all 270 agents — the single file out of 4,055 that disagreed across
platforms.

Not cosmetic. `source_path` is surfaced to the model: `_summary()` includes it in
every search result and `_specialist_prompt()` writes `Source: {path}` into the
composed prompt. **The text the model receives depended on which machine built
the plugin.**

Fixed with `rel.as_posix()`.

A Windows box and a Linux box are each internally self-consistent, and two runs
on either agree — so no amount of local repetition surfaces this. Only comparing
*across* platforms does, which is precisely what the manifest exists for. It
earned its keep on the first CI run.

## Renderer equivalence

`tools.json` states: *"the same `format` name guarantees byte-identical output,
so two tools may share a format only if their rendered files are identical."*
That is a contract with every consumer — the Agency Agents app branches on
`format` to pick a renderer — and it was asserted but never tested.

Among converted tools exactly **one** format is shared: `skill-md`, claimed by
both `antigravity` and `osaurus`. (`identity` is shared by `claude-code` and
`copilot`, but those install source files verbatim and have no converter.)
`tests/test-convert-determinism.sh` asserts those two trees are identical.

`qwen-md` and `zcode-md` are **distinct** format names, so the contract does not
bind them — but `convert_zcode`'s comment claims byte-identical output, so the
test reports on that claim without failing the build.

## Rules for anyone touching a converter

- **No timestamps in rendered output.** `convert.sh` reads the clock into
  `TODAY`, used only in the console banner; a comment marks it as a hazard. A
  date stamp in any rendered file would make every artifact differ on every run.
- **Pin collation** on anything whose order reaches output.
- **Write bytes, or pass `newline="\n"`.** Python text mode is CRLF on Windows.
- **Never rank with `Counter.most_common()`** — it breaks ties by insertion
  order, which `PYTHONHASHSEED` randomises per process. Sort fully, then slice.
- **Use `Path.as_posix()`, never `str(Path)`**, for any path that reaches output.
- **Regenerate the manifest** when output legitimately changes, and say so in the
  commit message.

## Current state

4,055 files, 14 tools, **0 CR bytes anywhere in generated output**. Independent
runs produce identical hashes for every order-sensitive artifact, and a manifest
generated on Windows verifies byte-for-byte on Ubuntu in CI — so conversion is
now reproducible across machines, not merely repeatable on one.
