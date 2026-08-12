#!/usr/bin/env python3
"""inventory.py -- deterministic content inventory of the agent corpus.

Emits one record per agent .md file (path, identity fields, content hash, size)
plus a summary. This is the fixed reference every later claim is measured
against: "this change is byte-neutral", "the corpus grew N%", "this agent
regressed" all require a frozen baseline to compare with.

    ./scripts/inventory.py --ref upstream-baseline-2026-08-13 --out metrics/inventory-baseline.json
    ./scripts/inventory.py --check metrics/inventory-baseline.json

PARSING NOTE -- read this before "fixing" anything below.

    This tool deliberately reproduces the CURRENT toolchain's frontmatter
    semantics (scripts/lib.sh get_field/get_body/slugify), byte for byte,
    including their known defects:

      * get_field matches the first line starting "<field>: " and keeps any
        additional leading whitespace, so an aligned "name:        Value"
        yields "       Value".
      * get_field takes ONE line, so a continued/multi-line YAML value is
        truncated at the first line.
      * get_field does not strip quotes, so a quoted value keeps its quotes.
      * get_body drops any body line that is exactly "---".

    That is the point. The inventory must record what the distribution layer
    actually sees today, not what a correct YAML parser would see. Phase 2
    introduces the authoritative parser (scripts/lib/frontmatter.py) and will
    report the divergence between the two as a first-class finding. Making this
    file "correct" early would silently erase that finding.

Determinism: stdlib only, sorted output, no timestamps, no host/user/env data,
LF newlines written explicitly (Python text mode would emit CRLF on Windows).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Legacy-faithful frontmatter helpers (mirror scripts/lib.sh)
# ---------------------------------------------------------------------------

def get_field(text: str, field: str) -> str:
    """Mirror of lib.sh get_field().

    awk: /^---$/ {fm++; next} fm==1 && $0 ~ "^field: " {sub("^field: ",""); print; exit}
    """
    fm = 0
    prefix = field + ": "
    for line in text.split("\n"):
        if line == "---":
            fm += 1
            continue
        if fm == 1 and line.startswith(prefix):
            return line[len(prefix):]
    return ""


def get_body(text: str) -> str:
    """Mirror of lib.sh get_body(): everything after the second '---' line.

    Lines equal to '---' are consumed by the fence counter and never printed,
    which means a horizontal rule in the body is dropped. Reproduced on purpose.
    """
    fm = 0
    out = []
    for line in text.split("\n"):
        if line == "---":
            fm += 1
            continue
        if fm >= 2:
            out.append(line)
    return "\n".join(out)


def slugify_lib_sh(value: str) -> str:
    """Mirror of lib.sh slugify().

        tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//'

    Operates on BYTES, because sed replaces each non-[a-z0-9] byte -- a
    multi-byte UTF-8 character becomes several dashes before the run-collapse.
    tr in the C locale lowercases ASCII only.
    """
    raw = value.encode("utf-8")
    lowered = bytes((c + 32) if 0x41 <= c <= 0x5A else c for c in raw)
    dashed = bytes(
        c if (0x61 <= c <= 0x7A or 0x30 <= c <= 0x39) else 0x2D for c in lowered
    )
    return re.sub(r"-+", "-", dashed.decode("ascii")).strip("-")


def slugify_hermes(value: str) -> str:
    """Mirror of scripts/build-hermes-plugin.py slugify().

    Unicode-aware .lower() and a regex over characters rather than bytes. Kept
    so the inventory can report whether the repo's two slug implementations
    agree on the real corpus (they must, or 13 tools and the Hermes index
    disagree about identity).
    """
    value = value.lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def is_agent(text: str) -> bool:
    """Mirror of lib.sh is_agent_file(): first line is exactly '---'."""
    return text.split("\n", 1)[0] == "---"


# ---------------------------------------------------------------------------
# Corpus sources: working tree or a git ref
# ---------------------------------------------------------------------------

def _git(args: list[str]) -> bytes:
    return subprocess.run(
        ["git"] + args, cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout


def divisions(ref: str | None) -> list[str]:
    """Division set from divisions.json -- never hardcoded (see its _note)."""
    if ref is None:
        raw = (REPO_ROOT / "divisions.json").read_bytes()
    else:
        raw = _git(["show", f"{ref}:divisions.json"])
    return sorted(json.loads(raw.decode("utf-8"))["divisions"].keys())


def read_corpus(ref: str | None) -> dict[str, bytes]:
    """Map of repo-relative POSIX path -> raw bytes for every agent .md file.

    With --ref, blobs are streamed via `git cat-file --batch`: no checkout, no
    writes, and any ref (including one on another branch) can be measured.
    """
    divs = set(divisions(ref))

    def in_division(path: str) -> bool:
        return path.endswith(".md") and path.split("/")[0] in divs

    if ref is None:
        paths = sorted(
            p.relative_to(REPO_ROOT).as_posix()
            for p in REPO_ROOT.rglob("*.md")
            if in_division(p.relative_to(REPO_ROOT).as_posix())
        )
        blobs = {p: (REPO_ROOT / p).read_bytes() for p in paths}
    else:
        listing = _git(["ls-tree", "-r", "--name-only", ref]).decode("utf-8")
        paths = sorted(p for p in listing.split("\n") if in_division(p))
        blobs = _cat_file_batch(ref, paths)

    return {p: b for p, b in blobs.items() if is_agent(b.decode("utf-8", "replace"))}


def _cat_file_batch(ref: str, paths: list[str]) -> dict[str, bytes]:
    """Stream many blobs through one `git cat-file --batch` process."""
    if not paths:
        return {}
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    query = "".join(f"{ref}:{p}\n" for p in paths).encode("utf-8")
    stdout, _ = proc.communicate(query)
    if proc.returncode != 0:
        raise SystemExit(f"git cat-file failed for ref {ref}")

    out: dict[str, bytes] = {}
    pos = 0
    for path in paths:
        nl = stdout.index(b"\n", pos)
        header = stdout[pos:nl].decode("utf-8")
        if header.endswith("missing"):
            raise SystemExit(f"blob missing in {ref}: {path}")
        size = int(header.split()[-1])
        start = nl + 1
        out[path] = stdout[start:start + size]
        pos = start + size + 1  # trailing newline after each blob
    return out


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def build(ref: str | None) -> dict:
    corpus = read_corpus(ref)
    records = []
    divergences = []

    for path in sorted(corpus):
        raw = corpus[path]
        text = raw.decode("utf-8")
        name = get_field(text, "name")
        slug = slugify_lib_sh(name)
        hermes_slug = slugify_hermes(name)
        if slug != hermes_slug:
            divergences.append(
                {"path": path, "lib_sh": slug, "build_hermes_plugin": hermes_slug}
            )
        records.append({
            "path": path,
            "division": path.split("/")[0],
            "filename_stem": path.rsplit("/", 1)[-1][:-3],
            "name": name,
            "name_slug": slug,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "body_word_count": len(get_body(text).split()),
        })

    per_division: dict[str, int] = {}
    for rec in records:
        per_division[rec["division"]] = per_division.get(rec["division"], 0) + 1

    stems = [r["filename_stem"] for r in records]
    slugs = [r["name_slug"] for r in records]

    return {
        "schema_version": SCHEMA_VERSION,
        "ref": ref or "WORKING_TREE",
        "summary": {
            "total_agents": len(records),
            "total_body_words": sum(r["body_word_count"] for r in records),
            "total_bytes": sum(r["byte_count"] for r in records),
            "divisions": len(per_division),
            "agents_per_division": dict(sorted(per_division.items())),
            # Identity health. Both namespaces are load-bearing for different
            # consumers; nothing in upstream CI enforces either one's uniqueness.
            "duplicate_filename_stems": sorted(
                {s for s in stems if stems.count(s) > 1}
            ),
            "duplicate_name_slugs": sorted({s for s in slugs if slugs.count(s) > 1}),
            "stem_slug_mismatches": sum(
                1 for r in records if r["filename_stem"] != r["name_slug"]
            ),
            "slug_implementation_divergences": divergences,
        },
        "agents": records,
    }


def dump(data: dict) -> bytes:
    """Serialize deterministically with LF newlines.

    Python text mode translates \\n to \\r\\n on Windows, which would make the
    same input produce different bytes per platform -- exactly the class of bug
    this project exists to catch. Write bytes.
    """
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", help="git ref to inventory (default: working tree)")
    ap.add_argument("--out", type=Path, help="write JSON here")
    ap.add_argument("--check", type=Path, help="recompute and diff; exit 1 on drift")
    args = ap.parse_args()

    if args.check and args.out:
        ap.error("--check and --out are mutually exclusive")

    data = build(args.ref)
    payload = dump(data)
    s = data["summary"]

    if args.check:
        prev = json.loads(args.check.read_bytes().decode("utf-8"))
        # Compare CORPUS STATE, not the `ref` label. `ref` records how a
        # snapshot was taken (a tag name vs WORKING_TREE); it is provenance, not
        # content. Including it made `--check` fail against a clean working tree
        # that is byte-identical to the tagged baseline, with nothing to report.
        if _comparable(prev) == _comparable(data):
            note = ""
            if prev.get("ref") != data["ref"]:
                note = f"  [ref differs: {prev.get('ref')} vs {data['ref']} -- content identical]"
            print(f"PASSED: inventory matches {args.check} "
                  f"({s['total_agents']} agents, {s['divisions']} divisions).{note}")
            return 0
        print(f"FAILED: inventory differs from {args.check}.", file=sys.stderr)
        _report_drift(prev, data)
        return 1

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(payload)
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(payload.decode("utf-8"))

    print(
        f"  ref={data['ref']}  agents={s['total_agents']}  "
        f"divisions={s['divisions']}  body_words={s['total_body_words']:,}",
        file=sys.stderr,
    )
    return 0


def _comparable(data: dict) -> dict:
    """The parts of an inventory that represent corpus state, minus provenance."""
    return {k: v for k, v in data.items() if k != "ref"}


def _report_drift(prev: dict, cur: dict) -> None:
    old = {r["path"]: r for r in prev.get("agents", [])}
    new = {r["path"]: r for r in cur["agents"]}
    for path in sorted(set(old) - set(new)):
        print(f"  REMOVED  {path}", file=sys.stderr)
    for path in sorted(set(new) - set(old)):
        print(f"  ADDED    {path}", file=sys.stderr)
    for path in sorted(set(old) & set(new)):
        changed = [k for k in new[path] if old[path].get(k) != new[path][k]]
        if changed:
            print(f"  CHANGED  {path}  ({', '.join(sorted(changed))})", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
