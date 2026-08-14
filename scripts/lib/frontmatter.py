"""The authoritative frontmatter parser for the skill engineering layer.

The repository has FOUR frontmatter readers, and they disagree:

  * scripts/lib.sh get_field       -- awk; used by convert.sh and install.sh
  * scripts/build-hermes-plugin.py -- Python, line-based
  * scripts/i18n/localize-agents-zh.ps1 -- PowerShell regex
  * this module                    -- real YAML

None of the first three is a YAML parser. They read one line per key, do not
strip quotes, and cannot represent a block value. That is not a theoretical
concern: `compat_get_field` here reproduces the first one EXACTLY so the
disagreement can be measured, and `divergence_report` measures it.

Scope: this module is for the engineering layer only. The distribution path
(convert.sh, install.sh, lib.sh) must keep zero runtime dependencies -- a user
installing agents must never need pip. Do not import this from those scripts.
Fixing them to use this parser is a separate, deliberate migration, because
their output is a contract with 16 tools.

    from lib.frontmatter import parse, validate, divergence_report

    fm, body, raw = parse("engineering/engineering-frontend-developer.md")
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "agent.schema.json"

# Named colours scripts/convert.sh resolve_opencode_color knows. Anything else
# falls back to grey #6B7280 in OpenCode. Kept here so the linter can report a
# colour that is contract-valid but will not render as intended.
KNOWN_COLOR_NAMES = frozenset({
    "cyan", "blue", "green", "red", "purple", "orange", "teal", "indigo",
    "pink", "gold", "amber", "neon-green", "neon-cyan", "metallic-blue",
    "yellow", "violet", "rose", "lime", "gray", "fuchsia",
})


class FrontmatterError(ValueError):
    """Raised when a file cannot be read as an agent."""


def split(raw: bytes) -> tuple[str, str]:
    """Return (frontmatter_block, body) from raw file bytes.

    Frontmatter is delimited by a line that is exactly '---'. Uses the SECOND
    such line as the terminator, so a horizontal rule later in the body is not
    mistaken for a fence.
    """
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise FrontmatterError("file does not open with a '---' frontmatter fence")
    try:
        close = lines.index("---", 1)
    except ValueError:
        raise FrontmatterError("frontmatter fence is never closed") from None
    return "\n".join(lines[1:close]), "\n".join(lines[close + 1:])


def parse(path: str | Path) -> tuple[dict, str, bytes]:
    """Parse an agent file. Returns (frontmatter dict, body, raw bytes)."""
    raw = Path(path).read_bytes()
    block, body = split(raw)
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML: {exc}") from None
    if data is None:
        raise FrontmatterError("frontmatter is empty")
    if not isinstance(data, dict):
        raise FrontmatterError(
            f"frontmatter is a {type(data).__name__}, expected a mapping"
        )
    return data, body, raw


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_bytes().decode("utf-8"))


def validate(frontmatter: dict, schema: dict | None = None) -> list[str]:
    """Return a sorted list of human-readable violations. Empty means valid."""
    import jsonschema

    schema = schema or load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in validator.iter_errors(frontmatter):
        where = ".".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{where}: {err.message}")
    return sorted(out)


def advisories(frontmatter: dict) -> list[str]:
    """Contract-valid values that will not behave as the author intends.

    Distinct from validate(): these are not schema violations, so they must not
    fail a build, but they are wrong in a way a human would want to know about.
    """
    out = []
    color = frontmatter.get("color", "")
    if isinstance(color, str) and not color.startswith("#"):
        if color.lower() not in KNOWN_COLOR_NAMES:
            out.append(
                f"color: '{color}' is not a name convert.sh knows, so OpenCode "
                f"renders it as the grey fallback #6B7280"
            )
    if "services" in frontmatter:
        out.append(
            "services: declared, but no converter carries this field into any "
            "of the 14 output formats"
        )
    return out


# ---------------------------------------------------------------------------
# Legacy compatibility -- for MEASURING disagreement, never for parsing
# ---------------------------------------------------------------------------

def compat_get_field(raw: bytes, field: str) -> str:
    """Byte-exact reproduction of scripts/lib.sh get_field().

        awk: /^---$/ {fm++; next}
             fm==1 && $0 ~ "^field: " {sub("^field: ",""); print; exit}

    Reproduces its defects on purpose: one line only, quotes not stripped, any
    additional leading whitespace preserved, block values invisible. This exists
    so divergence_report can quantify what the distribution layer actually sees.
    Do not use it to read a value.
    """
    fm = 0
    prefix = field + ": "
    for line in raw.decode("utf-8").split("\n"):
        if line == "---":
            fm += 1
            continue
        if fm == 1 and line.startswith(prefix):
            return line[len(prefix):]
    return ""


def divergence_report(path: str | Path) -> list[dict]:
    """Where the real parser and the legacy reader disagree for one file.

    Each entry: {field, legacy, canonical, kind}. `kind` classifies the cause so
    a corpus-wide report can be grouped:

      quotes-not-stripped -- legacy returns the value with its YAML quotes
      block-value         -- legacy returns '' for a structured value
      truncated           -- legacy sees a prefix of a multi-line value
      missing-in-legacy   -- canonical has a value legacy cannot see at all
      other               -- anything else, which should be investigated
    """
    frontmatter, _, raw = parse(path)
    out = []
    for field, canonical in frontmatter.items():
        legacy = compat_get_field(raw, field)
        if isinstance(canonical, str):
            if legacy == canonical:
                continue
            if legacy in (f'"{canonical}"', f"'{canonical}'"):
                kind = "quotes-not-stripped"
            elif legacy and canonical.startswith(legacy):
                kind = "truncated"
            elif not legacy:
                kind = "missing-in-legacy"
            else:
                kind = "other"
        else:
            kind = "block-value" if not legacy else "other"
        out.append({
            "field": field,
            "legacy": legacy,
            "canonical": canonical,
            "kind": kind,
        })
    return out
