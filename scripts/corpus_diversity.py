#!/usr/bin/env python3
"""corpus_diversity.py -- measure homogenization across the whole agent corpus.

    ./scripts/corpus_diversity.py --ref upstream-baseline-2026-08-13 --out metrics/diversity-baseline.json
    ./scripts/corpus_diversity.py --compare 459dce8 archive/fable-upgrade
    ./scripts/corpus_diversity.py --check metrics/diversity-baseline.json

WHY THIS EXISTS -- the measured case that motivates every metric below.

    scripts/check-agent-originality.sh flags an agent whose MAXIMUM pairwise
    similarity to any other agent crosses a threshold (WARN 20%, FAIL 40%). It
    is well calibrated for that question and stays exactly as it is.

    Branch archive/fable-upgrade is an autonomous mass "upgrade" that rewrote
    263 of 264 agents. Every existing check passed. Measured against its
    merge-base 459dce8:

        max pairwise similarity  4.7377% -> 4.7490%    (+0.2% -- INVISIBLE)
        median pairwise           0.000% ->  0.138%    (zero -> nonzero)
        p95 pairwise              0.000% ->  0.395%    (zero -> nonzero)
        p99 pairwise             0.0661% -> 0.6208%    (+839%)
        mean-of-max-per-file     0.2132% -> 0.6735%    (+216%)
        total corpus words       459,560 -> 520,223    (+13.2%)
        headers in >=50% of files      9 ->  11        (+22%)
        headers in >=75% of files      1 ->   4        (+300%)
        shared blocks (>=3 files)     11 ->  92        (+736%)
        duplicated word %        0.0629% -> 0.9702%    (+1442%)

    The corpus homogenized measurably across its entire distribution, gained
    60,663 words, and grew two near-universal boilerplate headers ("analytical
    discipline", 89% of files; "negative constraints never violate", 78%) --
    while the one statistic the existing gate watches did not move.

    Verbatim shared text is the sharpest signal of the set: duplicated_word_pct
    moved 15x more than any similarity percentile.

    So this tool deliberately does NOT report a single similarity number. It
    reports the distribution, the header vocabulary, the size, and the amount of
    text shared verbatim between files, because those are the axes that moved.

Tokenization is intentionally identical to check-agent-originality.sh (same
entity-neutralization list, same 8-word shingles). Only the STATISTIC differs.
Changing the tokenizer would make the two tools disagree about the same corpus.

Runtime: O(n^2) pairwise over ~270 agents (~36k pairs), a few seconds per ref.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import WORKING_TREE, comparable, dump_json, read_corpus  # noqa: E402

SCHEMA_VERSION = "1.0.0"

SHINGLE_K = 8      # matches check-agent-originality.sh
BLOCK_K = 12       # "shared boilerplate": a run this long repeated verbatim
BLOCK_MIN_FILES = 3

# Verbatim from scripts/check-agent-originality.sh. Neutralizing these means a
# find-replace re-skin (swap the country/platform, change little else) cannot
# hide behind a different proper noun. Keep the two lists in sync.
ENTITY = re.compile(
    r'\b(vietnam|vietnamese|china|chinese|douyin|tiktok|korea|korean|japan|japanese|'
    r'india|indian|indonesia|indonesian|thailand|thai|philippines|filipino|brazil|'
    r'brazilian|mexico|mexican|wechat|weixin|weibo|xiaohongshu|rednote|kuaishou|'
    r'bilibili|zhihu|baidu|shopee|lazada|zalo|tokopedia|taobao|tmall|pinduoduo|'
    r'instagram|facebook|youtube|reels|shorts|linkedin|twitter|threads|snapchat)\b')

HEADER = re.compile(r"^#{2,}\s+(.+?)\s*$", re.M)


# ---------------------------------------------------------------------------
# Tokenization (mirrors check-agent-originality.sh)
# ---------------------------------------------------------------------------

def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def tokens(text: str) -> list[str]:
    body = ENTITY.sub(" ", strip_frontmatter(text).lower())
    return re.sub(r"[^a-z0-9 ]", " ", body).split()


def shingles(words: list[str], k: int) -> set[str]:
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def normalize_header(raw: str) -> str:
    """Lowercase, drop non-letters (emoji, digits, punctuation), collapse spaces.

    '## 🧠 Your Identity & Memory' -> 'your identity memory'
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", raw.lower())).strip()


def rank(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
    """Top `limit` entries, ordered by count descending then key ascending.

    NOT Counter.most_common(): that breaks ties by insertion order, and these
    counters are fed from set iteration, whose order Python randomizes per
    process via PYTHONHASHSEED. Sorting most_common()'s output does not help --
    it has already chosen a different tied subset. Sort everything, then slice.
    """
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile. Documented so results stay reproducible."""
    if not sorted_values:
        return 0.0
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * p))]


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure(ref: str | None) -> dict:
    corpus = read_corpus(ref)
    paths = sorted(corpus)
    texts = {p: corpus[p].decode("utf-8") for p in paths}
    words = {p: tokens(texts[p]) for p in paths}
    shing = {p: shingles(words[p], SHINGLE_K) for p in paths}

    pairwise, per_agent = _pairwise(paths, shing)
    return {
        "schema_version": SCHEMA_VERSION,
        "ref": ref or WORKING_TREE,
        "parameters": {
            "shingle_k": SHINGLE_K,
            "block_k": BLOCK_K,
            "block_min_files": BLOCK_MIN_FILES,
            "percentile_method": "nearest-rank",
            "tokenizer": "check-agent-originality.sh (entity-neutralized, alphanumeric)",
        },
        "pairwise": pairwise,
        "vocabulary": _vocabulary(paths, texts),
        "size": _size(paths, words),
        "boilerplate": _boilerplate(paths, words),
        "per_agent": per_agent,
    }


def _pairwise(paths: list[str], shing: dict[str, set[str]]) -> tuple[dict, list]:
    """Full pairwise Jaccard distribution.

    The distribution -- not the maximum -- is what detects homogenization: a
    corpus can drift toward a shared template while no single pair ever becomes
    a near-duplicate.
    """
    sims: list[float] = []
    best: dict[str, tuple[float, str]] = {p: (0.0, "") for p in paths}

    for i, a in enumerate(paths):
        sa = shing[a]
        if not sa:
            continue
        la = len(sa)
        for b in paths[i + 1:]:
            sb = shing[b]
            if not sb:
                continue
            inter = len(sa & sb)
            if inter == 0:
                sims.append(0.0)
                continue
            j = inter / (la + len(sb) - inter)
            sims.append(j)
            if j > best[a][0]:
                best[a] = (j, b)
            if j > best[b][0]:
                best[b] = (j, a)

    sims.sort()
    maxes = [v[0] for v in best.values()]
    return (
        {
            "pairs": len(sims),
            "median_pct": round(percentile(sims, 0.50) * 100, 4),
            "p95_pct": round(percentile(sims, 0.95) * 100, 4),
            "p99_pct": round(percentile(sims, 0.99) * 100, 4),
            "max_pct": round((sims[-1] if sims else 0.0) * 100, 4),
            "mean_of_max_per_file_pct": round(
                (sum(maxes) / len(maxes) if maxes else 0.0) * 100, 4
            ),
            "pairs_ge_5pct": sum(1 for s in sims if s >= 0.05),
            "pairs_ge_10pct": sum(1 for s in sims if s >= 0.10),
            "pairs_ge_20pct": sum(1 for s in sims if s >= 0.20),
        },
        [
            {
                "path": p,
                "max_similarity_pct": round(best[p][0] * 100, 4),
                "closest": best[p][1],
            }
            for p in paths
        ],
    )


def _vocabulary(paths: list[str], texts: dict[str, str]) -> dict:
    """Section-header vocabulary and how widely each header is shared.

    A library converging on one template shows up here first: the count of
    headers present in most files rises even when prose stays distinct.
    """
    files_per_header: Counter[str] = Counter()
    for p in paths:
        seen = {
            normalize_header(h)
            for h in HEADER.findall(strip_frontmatter(texts[p]))
        }
        files_per_header.update(h for h in seen if h)

    n = len(paths)
    return {
        "distinct_headers": len(files_per_header),
        "headers_in_25pct_files": sum(1 for c in files_per_header.values() if c >= n * 0.25),
        "headers_in_50pct_files": sum(1 for c in files_per_header.values() if c >= n * 0.50),
        "headers_in_75pct_files": sum(1 for c in files_per_header.values() if c >= n * 0.75),
        "top_headers": [
            {"header": h, "files": c, "pct_of_corpus": round(c / n * 100, 1)}
            for h, c in rank(files_per_header, 20)
        ],
    }


def _size(paths: list[str], words: dict[str, list[str]]) -> dict:
    """Corpus and per-agent size. Instruction bloat is a tracked regression."""
    counts = sorted(len(words[p]) for p in paths)
    total = sum(counts)
    per_division: defaultdict[str, list[int]] = defaultdict(list)
    for p in paths:
        per_division[p.split("/")[0]].append(len(words[p]))
    return {
        "agents": len(paths),
        "total_words": total,
        "mean_words": round(total / len(counts), 1) if counts else 0,
        "median_words": percentile(counts, 0.50),
        "p10_words": percentile(counts, 0.10),
        "p90_words": percentile(counts, 0.90),
        "mean_words_per_division": {
            d: round(sum(v) / len(v), 1) for d, v in sorted(per_division.items())
        },
    }


def _boilerplate(paths: list[str], words: dict[str, list[str]]) -> dict:
    """Text repeated verbatim across files.

    Counts BLOCK_K-word runs appearing in at least BLOCK_MIN_FILES files, then
    measures how many words of the corpus sit inside such a run. Unlike pairwise
    similarity this catches a template fragment sprinkled across many files,
    where no single pair looks alike.
    """
    files_per_block: Counter[str] = Counter()
    for p in paths:
        files_per_block.update(shingles(words[p], BLOCK_K))

    shared = {b for b, c in files_per_block.items() if c >= BLOCK_MIN_FILES}

    covered_total = 0
    for p in paths:
        w = words[p]
        covered = bytearray(len(w))
        for i in range(max(0, len(w) - BLOCK_K + 1)):
            if " ".join(w[i:i + BLOCK_K]) in shared:
                for j in range(i, i + BLOCK_K):
                    covered[j] = 1
        covered_total += sum(covered)

    total_words = sum(len(words[p]) for p in paths)
    return {
        "shared_blocks": len(shared),
        "duplicated_words": covered_total,
        "duplicated_word_pct": round(covered_total / total_words * 100, 4) if total_words else 0.0,
        "top_blocks": [
            {"files": c, "text": b}
            for b, c in rank(files_per_block, 10)
            if c >= BLOCK_MIN_FILES
        ],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

# (json path, human label, higher-is-worse)
TRACKED = [
    ("pairwise.median_pct", "median pairwise similarity %", True),
    ("pairwise.p95_pct", "p95 pairwise similarity %", True),
    ("pairwise.p99_pct", "p99 pairwise similarity %", True),
    ("pairwise.max_pct", "max pairwise similarity %", True),
    ("pairwise.mean_of_max_per_file_pct", "mean-of-max per file %", True),
    ("vocabulary.distinct_headers", "distinct headers", False),
    ("vocabulary.headers_in_50pct_files", "headers in >=50% of files", True),
    ("vocabulary.headers_in_75pct_files", "headers in >=75% of files", True),
    ("size.total_words", "total corpus words", True),
    ("size.mean_words", "mean words per agent", True),
    ("boilerplate.shared_blocks", "shared blocks (>=3 files)", True),
    ("boilerplate.duplicated_word_pct", "duplicated word %", True),
]


def dig(data: dict, dotted: str):
    for part in dotted.split("."):
        data = data[part]
    return data


# Output contract: stdout carries machine-readable JSON ONLY; every
# human-readable line goes to stderr. Otherwise `--out`-less runs redirected to
# a file capture the summary table too, and the artifact is not valid JSON.
def say(*args) -> None:
    print(*args, file=sys.stderr)


def print_compare(a: dict, b: dict) -> None:
    say(f"\nCorpus diversity: {a['ref']}  ->  {b['ref']}\n")
    say(f"  {'metric':<34} {'before':>14} {'after':>14} {'change':>14}")
    say(f"  {'-' * 34} {'-' * 14} {'-' * 14} {'-' * 14}")
    for key, label, _ in TRACKED:
        va, vb = dig(a, key), dig(b, key)
        if va == 0:
            change = "0 -> nonzero" if vb else "unchanged"
        else:
            change = f"{(vb - va) / va * 100:+.1f}%"
        say(f"  {label:<34} {va:>14,} {vb:>14,} {change:>14}")

    only_b = {h["header"] for h in b["vocabulary"]["top_headers"]} - {
        h["header"] for h in a["vocabulary"]["top_headers"]
    }
    if only_b:
        say("\n  New headers entering the top 20:")
        for h in sorted(only_b):
            entry = next(x for x in b["vocabulary"]["top_headers"] if x["header"] == h)
            say(f"    {entry['files']:>4} files ({entry['pct_of_corpus']:>5.1f}%)  {h}")
    say("")


def print_summary(d: dict) -> None:
    say(f"\nCorpus diversity: {d['ref']}\n")
    for key, label, _ in TRACKED:
        say(f"  {label:<34} {dig(d, key):>14,}")
    say("")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", help="git ref to measure (default: working tree)")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="measure two refs and print the delta")
    ap.add_argument("--out", type=Path, help="write JSON here")
    ap.add_argument("--check", type=Path, help="recompute and diff; exit 1 on drift")
    args = ap.parse_args()

    if args.compare:
        before, after = (measure(r) for r in args.compare)
        print_compare(before, after)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(dump_json({"before": before, "after": after}))
            say(f"Wrote {args.out}")
        return 0

    data = measure(args.ref)

    if args.check:
        prev = json.loads(args.check.read_bytes().decode("utf-8"))
        if comparable(prev) == comparable(data):
            print(f"PASSED: diversity metrics match {args.check}.")
            return 0
        print(f"FAILED: diversity metrics differ from {args.check}.", file=sys.stderr)
        for key, label, _ in TRACKED:
            va, vb = dig(prev, key), dig(data, key)
            if va != vb:
                print(f"  {label:<34} {va:>14,} -> {vb:>14,}", file=sys.stderr)
        return 1

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(dump_json(data))
        say(f"Wrote {args.out}")
    else:
        sys.stdout.buffer.write(dump_json(data))

    print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
