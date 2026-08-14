"""Corpus access: read agent files from the working tree or any git ref.

Single implementation shared by every engineering-layer tool, so "what counts as
an agent" is defined once. The division set always comes from divisions.json --
never a hardcoded list (see that file's _note, and the comments in
scripts/check-agent-originality.sh and scripts/build-hermes-plugin.py, which
make the same choice for the same reason).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

WORKING_TREE = "WORKING_TREE"


def git(args: list[str]) -> bytes:
    return subprocess.run(
        ["git"] + args, cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout


def divisions(ref: str | None = None) -> list[str]:
    """Division names from divisions.json at `ref` (or the working tree)."""
    if ref is None:
        raw = (REPO_ROOT / "divisions.json").read_bytes()
    else:
        raw = git(["show", f"{ref}:divisions.json"])
    return sorted(json.loads(raw.decode("utf-8"))["divisions"].keys())


def is_agent(text: str) -> bool:
    """Mirror of lib.sh is_agent_file(): first line is exactly '---'."""
    return text.split("\n", 1)[0] == "---"


def read_corpus(ref: str | None = None) -> dict[str, bytes]:
    """Map repo-relative POSIX path -> raw bytes for every agent .md file.

    With a ref, blobs stream through one `git cat-file --batch` process: no
    checkout, no writes, and any ref can be measured -- including branches such
    as archive/fable-upgrade that must never be checked out over the tree.
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
        listing = git(["ls-tree", "-r", "--name-only", ref]).decode("utf-8")
        paths = sorted(p for p in listing.split("\n") if in_division(p))
        blobs = cat_file_batch(ref, paths)

    return {p: b for p, b in blobs.items() if is_agent(b.decode("utf-8", "replace"))}


def cat_file_batch(ref: str, paths: list[str]) -> dict[str, bytes]:
    """Stream many blobs through a single `git cat-file --batch` process."""
    if not paths:
        return {}
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    stdout, _ = proc.communicate("".join(f"{ref}:{p}\n" for p in paths).encode("utf-8"))
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
        pos = start + size + 1  # git writes a newline after each blob
    return out


def dump_json(data: dict) -> bytes:
    """Deterministic JSON bytes with LF newlines.

    Python text mode emits CRLF on Windows, which would make identical input
    produce different bytes per platform -- the exact class of defect this
    project exists to catch. Always write the returned bytes, never str.
    """
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def comparable(data: dict) -> dict:
    """An artifact minus provenance, for --check comparisons.

    `ref` records how a snapshot was taken (a tag name vs WORKING_TREE). It is
    provenance, not corpus state: including it makes --check fail against a
    clean working tree that is byte-identical to the tagged baseline.
    """
    return {k: v for k, v in data.items() if k != "ref"}
