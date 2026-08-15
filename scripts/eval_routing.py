#!/usr/bin/env python3
"""eval_routing.py -- can the right specialist actually be found?

    ./scripts/eval_routing.py                 # report
    ./scripts/eval_routing.py --check         # fail if metrics/routing-baseline.json is stale
    ./scripts/eval_routing.py --gate          # fail on a threshold breach
    ./scripts/eval_routing.py --explain c018  # show every query tried for one case

WHAT THIS MEASURES, AND WHAT IT DELIBERATELY DOES NOT

The router skill works in two steps: a model picks search terms, then greps
`index.md`. Only the second step is deterministic, so only the second step is
measured here. This harness answers:

    Given the words a user actually used, is the correct specialist REACHABLE
    in the index at all, and how much noise comes with it?

That is a property of the index, not of the model. It is also a hard ceiling on
routing accuracy: if the right agent cannot be reached by any term drawn from
the task, no amount of model cleverness will find it, and the fix is to change
the index rather than the prompt. Cases that fail here are actionable defects.

Judging whether a model picks WELL among reachable candidates needs a model in
the loop, which costs money on every run. That is deliberately not in CI while
the CI budget is unsettled; see docs/routing-evaluation.md.

THE TAUTOLOGY TRAP

A benchmark whose task text is derived from the agent's own description tests
whether text matches itself. It scores near 100% and proves nothing. So every
case is written in user vocabulary, and this script MEASURES the token overlap
between each case and its expected agent's description and reports the
distribution. Rising overlap means the benchmark is getting easier, not that
routing is getting better. A negative control -- scoring every case against the
wrong agent -- runs on every invocation for the same reason.

THREE STRATEGIES

  bag          every content word OR'd together. The naive strategy the router
               skill explicitly warns against. Answer-blind.
  distinctive  the rarest adjacent word pair in the task that matches anything
               at all. An answer-blind proxy for "pick a distinctive phrase",
               which is what the skill tells the model to do.
  ceiling      ORACLE. The best query, word or phrase, that reaches the target.
               Not a strategy -- an upper bound. Labelled as such everywhere.

bag and distinctive never look at the expected answer when choosing a query.
Only the ceiling does, and it exists to separate "the index cannot express this"
from "the search strategy was poor".
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import frontmatter as fm  # noqa: E402
from lib.corpus import REPO_ROOT, dump_json, read_corpus  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

INDEX = REPO_ROOT / "plugins" / "router" / "skills" / "agency-router" / "index.md"
CASES = REPO_ROOT / "eval" / "routing" / "cases.jsonl"
BASELINE = REPO_ROOT / "metrics" / "routing-baseline.json"
THRESHOLDS = REPO_ROOT / "metrics" / "routing-thresholds.json"

# Deliberately conservative. Removing a word can only make search WEAKER here,
# so a short list is the safe error: it leaves noise in rather than silently
# deleting the one term that would have found the agent. Words are dropped only
# when they carry no domain signal in any division.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those there here
i we you they it its it's our my your their his her them us me
is are was were be been being am do does did doing done
have has had having get gets got getting
can could should would will shall may might must
of in on at to for with without from by as into onto over under
about after before during between across through
not no nor so too very just only also even still yet
what which who whom whose when where why how
some any all both each few more most other another such own same
need needs needed want wants wanted like likes
one two three
please help thing things stuff way ways lot lots bit
""".split())

TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
MIN_TOKEN = 3


def tokens(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped from the edges."""
    return [t.strip(".-") for t in TOKEN.findall(text.lower()) if t.strip(".-")]


def content(text: str) -> list[str]:
    """Task tokens a searcher would plausibly type, in original order."""
    return [t for t in tokens(text)
            if t not in STOPWORDS and (len(t) >= MIN_TOKEN or t.isdigit())]


ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# Truncation, not linguistics. Grep matches substrings, so "hire" finds "hires"
# and "hiring" while "hires" finds neither -- the fix available to a searcher is
# to CUT the word back, and reconstructing a lemma ("companies" -> "company")
# would not help a substring match at all. Ordered longest suffix first.
SUFFIXES = (("ing", 6), ("ers", 6), ("ies", 6), ("ion", 6), ("es", 5),
            ("ed", 5), ("er", 5), ("s", 4))


def stem(word: str) -> str:
    for suffix, min_len in SUFFIXES:
        if len(word) >= min_len and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def load_index() -> list[dict]:
    """Parse the shipped router index -- the artifact a consumer actually greps.

    The id must match the canonical pattern. Splitting on " | " alone is not
    enough: the index's own header line documents the format as
    "`id | division | name | description`", which splits into exactly four
    fields and was silently counted as a 271st agent until this check existed.
    """
    entries = []
    for line in INDEX.read_bytes().decode("utf-8").splitlines():
        parts = line.split(" | ")
        if len(parts) != 4 or line.startswith("#"):
            continue
        agent_id, division, name, description = (p.strip() for p in parts)
        if not ID_PATTERN.match(agent_id):
            continue
        entries.append({
            "id": agent_id,
            "division": division,
            "name": name,
            "description": description,
            "line": line,
        })
    return entries


def index_from_ref(ref: str) -> list[dict]:
    """Rebuild the equivalent index from raw frontmatter at an arbitrary ref.

    The shipped index is generated from registry.json, which only exists from
    Phase 4 onward, and keys on the id field, which only exists from Phase 3.
    Reconstructing the same four fields straight from frontmatter lets this
    harness run against archive/fable-upgrade -- a corpus that predates both --
    which is the only way to ASK whether homogenization damages routing instead
    of assuming it must. The id is the filename stem by definition (see
    docs/identity.md), so ids line up across refs with no mapping table.

    A file whose frontmatter will not parse is skipped rather than fatal: an
    older ref is allowed to be malformed, and refusing to measure it would mean
    having no known-bad comparison at all.
    """
    entries = []
    for path, raw in sorted(read_corpus(ref).items()):
        try:
            block, _ = fm.split(raw)
            data = yaml.safe_load(block) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        agent_id = path.rsplit("/", 1)[-1][:-3]
        name = str(data.get("name", agent_id))
        description = str(data.get("description", "")).replace("\n", " ").strip()
        division = path.split("/")[0]
        entries.append({
            "id": agent_id,
            "division": division,
            "name": name,
            "description": description,
            "line": f"{agent_id} | {division} | {name} | {description}",
        })
    return entries


def load_cases() -> list[dict]:
    cases = []
    for raw in CASES.read_bytes().decode("utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("//"):
            continue
        cases.append(json.loads(raw))
    return cases


def matches(pattern: str, entries: list[dict]) -> list[str]:
    """Exactly what `Grep pattern=... path=index.md` would return: ids of
    matching lines, case-insensitive, in file order."""
    rx = re.compile(pattern, re.IGNORECASE)
    return [e["id"] for e in entries if rx.search(e["line"])]


def phrase(a: str, b: str) -> str:
    return rf"{re.escape(a)}\s+{re.escape(b)}"


def candidates(task: str) -> tuple[list[str], list[str]]:
    """(single-word queries, adjacent-phrase queries) drawn from the task.

    Phrases are built from words ADJACENT IN THE ORIGINAL TEXT that are both
    content words, so they are real phrases a person could lift out of the
    sentence -- "app store", "screen reader", "error budget". Pairing content
    words after stopword removal would invent phrases nobody would ever type.
    """
    raw = tokens(task)
    singles, phrases = [], []
    seen_s, seen_p = set(), set()
    for i, tok in enumerate(raw):
        if tok in STOPWORDS or (len(tok) < MIN_TOKEN and not tok.isdigit()):
            continue
        if tok not in seen_s:
            seen_s.add(tok)
            singles.append(tok)
        if i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in STOPWORDS or (len(nxt) < MIN_TOKEN and not nxt.isdigit()):
                continue
            p = phrase(tok, nxt)
            if p not in seen_p:
                seen_p.add(p)
                phrases.append(p)
    return singles, phrases


def strategy_bag(task: str, entries: list[dict]) -> dict:
    """Every content word OR'd -- the word soup the skill warns against."""
    singles, _ = candidates(task)
    if not singles:
        return {"query": None, "matched": []}
    q = "|".join(re.escape(w) for w in singles)
    return {"query": q, "matched": matches(q, entries)}


def strategy_phrases(task: str, entries: list[dict]) -> dict:
    """Every adjacent phrase from the task tried in turn, results unioned.

    NOT a fair test of the router skill's advice, and must not be read as one.
    The skill says to search a distinctive DOMAIN phrase; this lifts phrases
    verbatim out of the user's sentence, and nobody competent greps "four
    thousand". What it measures is a property of the index: how often a user's
    own wording survives as a literal phrase in a description. The answer turns
    out to be almost never, which is the point -- it is evidence for how much
    routing leans on the model translating the task first.
    """
    _, phrases = candidates(task)
    seen: list[str] = []
    for q in phrases:
        for agent_id in matches(q, entries):
            if agent_id not in seen:
                seen.append(agent_id)
    return {"query": f"{len(phrases)} phrase(s)", "matched": seen}


def strategy_stemmed(task: str, entries: list[dict]) -> dict:
    """Every content word truncated to its stem, then OR'd. Answer-blind.

    The gap between this and the plain bag is the share of routing failures that
    are pure morphology -- a task saying "hires" against a description saying
    "new hire support" -- rather than a real vocabulary gap. That distinction
    matters because the two have completely different fixes: one is a rule the
    skill can state in a sentence, the other needs the model to know the domain.
    """
    singles, _ = candidates(task)
    stems = []
    for word in singles:
        s = stem(word)
        if len(s) >= MIN_TOKEN and s not in stems:
            stems.append(s)
    if not stems:
        return {"query": None, "matched": []}
    q = "|".join(re.escape(s) for s in stems)
    return {"query": q, "matched": matches(q, entries)}


def strategy_narrowest(task: str, entries: list[dict], expect: list[str]) -> dict:
    """ORACLE. The narrowest task-derived query that still reaches the target.

    This is not a strategy anyone could run -- it is told the answer. It exists
    to separate two very different failures: "the right agent was never in any
    result set" from "it was in there, buried". Its RECALL is provably identical
    to the bag's (a phrase can only match a line if its first word does too), so
    only its noise figure carries information.
    """
    singles, phrases = candidates(task)
    best = None
    for q in phrases + [re.escape(w) for w in singles]:
        m = matches(q, entries)
        if not any(a in m for a in expect):
            continue
        key = (len(m), q)
        if best is None or key < best[0]:
            best = (key, q, m)
    if best is None:
        return {"query": None, "matched": []}
    return {"query": best[1], "matched": best[2]}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def evaluate(cases: list[dict], entries: list[dict],
             expect_of=None) -> list[dict]:
    """Score every case. `expect_of` overrides the expected agents, which is how
    the negative control reuses this code path unchanged."""
    by_id = {e["id"]: e for e in entries}
    rows = []
    for case in cases:
        expect = expect_of(case) if expect_of else case["expect"]
        task = case["task"]
        bag = strategy_bag(task, entries)
        phr = strategy_phrases(task, entries)
        stm = strategy_stemmed(task, entries)
        narrow = strategy_narrowest(task, entries, expect)

        target = by_id.get(expect[0])
        overlap = jaccard(
            set(content(task)),
            set(content(f"{target['name']} {target['description']}")) if target else set(),
        )

        rows.append({
            "case": case["case"],
            "kind": case.get("kind", "independent"),
            "expect": expect,
            "bag_hit": any(a in bag["matched"] for a in expect),
            "bag_matches": len(bag["matched"]),
            "verbatim_phrase_hit": any(a in phr["matched"] for a in expect),
            "verbatim_phrase_matches": len(phr["matched"]),
            "stemmed_hit": any(a in stm["matched"] for a in expect),
            "stemmed_matches": len(stm["matched"]),
            "reachable": bool(narrow["matched"]),
            "narrowest_matches": len(narrow["matched"]),
            "narrowest_query": narrow["query"],
            "description_overlap": round(overlap, 4),
        })
    return rows


def summarise(rows: list[dict], key_hit: str, key_matches: str) -> dict:
    hits = [r for r in rows if r[key_hit]]
    counts = [r[key_matches] for r in rows if r[key_matches]]
    return {
        "hit_pct": round(100.0 * len(hits) / len(rows), 2) if rows else 0.0,
        "hits": len(hits),
        "misses": len(rows) - len(hits),
        "median_matches": statistics.median(counts) if counts else 0,
        "mean_matches": round(statistics.fmean(counts), 2) if counts else 0.0,
        "max_matches": max(counts) if counts else 0,
    }


def with_lift(rows: list[dict], control: list[dict],
              key_hit: str, key_matches: str) -> dict:
    """Summarise a strategy alongside what it scores against the WRONG agent.

    A raw hit rate is not comparable across strategies that match different
    amounts of the index. Broadening a query raises the hit rate for free, and
    the control rises with it. Lift -- hit rate minus control rate -- is the
    part that is actually about finding the right agent, and it is the only
    number here worth comparing between rows.
    """
    st = summarise(rows, key_hit, key_matches)
    ct = summarise(control, key_hit, key_matches)
    st["control_hit_pct"] = ct["hit_pct"]
    st["lift_over_control"] = round(st["hit_pct"] - ct["hit_pct"], 2)
    return st


def build_report(ref: str | None = None) -> dict:
    entries = index_from_ref(ref) if ref else load_index()
    cases = load_cases()
    rows = evaluate(cases, entries)

    # Negative control: score each case against the NEXT case's expected agent.
    # A rotation, not a shuffle, so it is deterministic and needs no seed. If
    # these hit rates are not near zero the metric is measuring vocabulary
    # rather than correctness, and every other number here is noise.
    order = [c["expect"] for c in cases]
    rotated = {c["case"]: order[(i + 1) % len(order)]
               for i, c in enumerate(cases)}
    control = evaluate(cases, entries, expect_of=lambda c: rotated[c["case"]])

    overlaps = sorted(r["description_overlap"] for r in rows)
    by_kind: dict[str, int] = {}
    for c in cases:
        by_kind[c.get("kind", "independent")] = by_kind.get(c.get("kind", "independent"), 0) + 1

    unreachable = sorted(r["case"] for r in rows if not r["reachable"])
    known_ids = {e["id"] for e in entries}
    unknown = sorted({a for c in cases for a in c["expect"] if a not in known_ids})

    return {
        "_note": ("Generated by scripts/eval_routing.py. Committed so a change in "
                  "routing quality shows up as a reviewable diff, and CI verifies it "
                  "is current. Per-case rows are included deliberately: an aggregate "
                  "that improves while one case regresses is exactly the failure this "
                  "project exists to prevent."),
        "index": {"path": INDEX.relative_to(REPO_ROOT).as_posix() if not ref
                  else f"reconstructed from frontmatter at {ref}",
                  "agents": len(entries)},
        "cases": {"total": len(cases), "by_kind": dict(sorted(by_kind.items())),
                  "unknown_expected_ids": unknown},
        "literal_reachability": {
            "_note": ("Share of cases where SOME word the user actually typed appears "
                      "in the right agent's index line. This is not a ceiling on "
                      "routing accuracy -- a model can translate 'second pair of eyes' "
                      "into 'code review' before grepping, and the harness cannot. It "
                      "is the share of tasks where routing does NOT depend on that "
                      "translation, and the misses name exactly where it does."),
            "pct": round(100.0 * sum(1 for r in rows if r["reachable"]) / len(rows), 2)
            if rows else 0.0,
            "reachable": sum(1 for r in rows if r["reachable"]),
            "requires_expansion": unreachable,
        },
        "strategies": {
            "_note": ("Recall is identical for bag and narrowest_oracle by "
                      "construction: a phrase can only match a line whose text "
                      "contains its first word, so anything a narrow query finds the "
                      "word soup finds too. The pair differ only in NOISE, and that "
                      "difference is the entire argument for searching narrowly. "
                      "verbatim_phrases is NOT a strategy evaluation -- see the "
                      "docstring of strategy_phrases()."),
            "bag": with_lift(rows, control, "bag_hit", "bag_matches"),
            "verbatim_phrases": with_lift(rows, control, "verbatim_phrase_hit",
                                          "verbatim_phrase_matches"),
            "stemmed": with_lift(rows, control, "stemmed_hit", "stemmed_matches"),
            "narrowest_oracle": with_lift(rows, control, "reachable",
                                          "narrowest_matches"),
        },
        "morphology_headroom": {
            "_note": ("Cases the plain word bag misses but stemming reaches. These "
                      "fail on word endings alone, not on domain vocabulary, and the "
                      "fix is one sentence of guidance: grep the stem. Everything "
                      "still missing after stemming is a genuine semantic gap."),
            "recovered_by_stemming": sorted(
                r["case"] for r in rows if r["stemmed_hit"] and not r["bag_hit"]),
            "lost_by_stemming": sorted(
                r["case"] for r in rows if r["bag_hit"] and not r["stemmed_hit"]),
            "semantic_gap_remaining": sorted(
                r["case"] for r in rows
                if not r["stemmed_hit"] and not r["bag_hit"]),
        },
        "benchmark_leakage": {
            "_note": ("Token overlap between each case and its expected agent's index "
                      "line. This is a property of the BENCHMARK, not of routing. If it "
                      "rises, the cases are being written in the agents' own vocabulary "
                      "and the scores above stop meaning anything."),
            "median_overlap": round(statistics.median(overlaps), 4) if overlaps else 0.0,
            "mean_overlap": round(statistics.fmean(overlaps), 4) if overlaps else 0.0,
            "max_overlap": max(overlaps) if overlaps else 0.0,
            "cases_over_0_25": sorted(r["case"] for r in rows
                                      if r["description_overlap"] > 0.25),
        },
        "negative_control": {
            "_note": ("Every case scored against the WRONG agent (expectations rotated "
                      "by one). These must stay near zero. A high control score means "
                      "the queries match everything, so a 'hit' proves nothing."),
            "bag_hit_pct": summarise(control, "bag_hit", "bag_matches")["hit_pct"],
            "verbatim_phrase_hit_pct": summarise(control, "verbatim_phrase_hit",
                                                 "verbatim_phrase_matches")["hit_pct"],
            "stemmed_hit_pct": summarise(control, "stemmed_hit",
                                         "stemmed_matches")["hit_pct"],
            "narrowest_hit_pct": summarise(control, "reachable",
                                           "narrowest_matches")["hit_pct"],
        },
        "per_case": rows,
    }


def gate(report: dict) -> list[str]:
    if not THRESHOLDS.exists():
        return []
    cfg = json.loads(THRESHOLDS.read_bytes().decode("utf-8"))["thresholds"]
    failures = []

    def value(path: str):
        node = report
        for part in path.split("."):
            node = node[part]
        return node

    for path, rule in sorted(cfg.items()):
        got = value(path)
        if "min" in rule and got < rule["min"]:
            failures.append(f"{path}: {got} < min {rule['min']}")
        if "max" in rule and got > rule["max"]:
            failures.append(f"{path}: {got} > max {rule['max']}")
    return failures


def explain(case_id: str) -> int:
    entries = load_index()
    cases = {c["case"]: c for c in load_cases()}
    case = cases.get(case_id)
    if case is None:
        print(f"No such case: {case_id}", file=sys.stderr)
        return 1
    print(f"{case['case']}  [{case.get('kind')}]  expect={case['expect']}")
    print(f"  task: {case['task']}")
    singles, phrases = candidates(case["task"])
    print(f"\n  phrases tried ({len(phrases)}):")
    for q in phrases:
        m = matches(q, entries)
        mark = "HIT " if any(a in m for a in case["expect"]) else "    "
        print(f"    {mark}{len(m):>4} matches  {q}")
    print(f"\n  single words tried ({len(singles)}):")
    for w in singles:
        m = matches(re.escape(w), entries)
        mark = "HIT " if any(a in m for a in case["expect"]) else "    "
        print(f"    {mark}{len(m):>4} matches  {w}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify metrics/routing-baseline.json is current")
    ap.add_argument("--gate", action="store_true",
                    help="fail on a threshold breach")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    ap.add_argument("--explain", metavar="CASE", help="show every query tried")
    ap.add_argument("--ref", metavar="REF",
                    help="measure a git ref instead of the shipped index; the "
                         "index is rebuilt from frontmatter so refs predating "
                         "registry.json can be compared. Never writes a baseline.")
    args = ap.parse_args()

    if args.explain:
        return explain(args.explain)

    report = build_report(args.ref)
    blob = dump_json(report)

    # Not a threshold -- a correctness failure. An expectation naming an agent
    # that does not exist means a rename slipped past, and every score computed
    # against it is silently wrong rather than merely low. Skipped for --ref,
    # where a missing agent just means the old corpus did not have it yet.
    unknown = report["cases"]["unknown_expected_ids"]
    if unknown and not args.ref:
        print(f"FAILED: {len(unknown)} expected agent id(s) do not exist:",
              file=sys.stderr)
        for agent_id in unknown:
            print(f"  {agent_id}", file=sys.stderr)
        print("\nA case expects an agent that is not in the index. Either the agent "
              "was renamed (check-identity.py should have caught that) or the case "
              "has a typo. Fix eval/routing/cases.jsonl.", file=sys.stderr)
        return 1

    if args.json:
        sys.stdout.buffer.write(blob)
        return 0

    if args.check:
        if not BASELINE.exists():
            print(f"FAILED: {BASELINE} is missing. Run ./scripts/eval_routing.py",
                  file=sys.stderr)
            return 1
        if BASELINE.read_bytes() != blob:
            print("FAILED: metrics/routing-baseline.json is stale.\n", file=sys.stderr)
            print("Routing behaviour changed. Regenerate and review the diff:",
                  file=sys.stderr)
            print("  ./scripts/eval_routing.py", file=sys.stderr)
            return 1
        print(f"PASSED: routing baseline current "
              f"({report['cases']['total']} cases, {report['index']['agents']} agents).")
        return 0

    if not args.ref:
        BASELINE.write_bytes(blob)

    s = report["strategies"]
    print(f"Index: {report['index']['agents']} agents   "
          f"Cases: {report['cases']['total']} {report['cases']['by_kind']}")
    print(f"\nLiteral reachability: {report['literal_reachability']['pct']}%  "
          f"({report['literal_reachability']['reachable']}/"
          f"{report['cases']['total']} tasks share a word with the right agent)")

    print(f"\n{'query':<22}{'hit%':>8}{'control%':>10}{'lift':>8}"
          f"{'median noise':>14}{'max noise':>11}")
    for name, label in (("bag", "every word OR'd"),
                        ("verbatim_phrases", "user's own phrases"),
                        ("stemmed", "stems OR'd"),
                        ("narrowest_oracle", "narrowest (oracle)")):
        st = s[name]
        print(f"{label:<22}{st['hit_pct']:>8}{st['control_hit_pct']:>10}"
              f"{st['lift_over_control']:>8}{st['median_matches']:>14}"
              f"{st['max_matches']:>11}")
    print("  lift = hit% minus the same query's score against the WRONG agent.")
    print("  Only lift is comparable between rows: widening a query raises both.")

    mh = report["morphology_headroom"]
    print(f"morphology: {len(mh['recovered_by_stemming'])} case(s) recovered by "
          f"stemming, {len(mh['lost_by_stemming'])} lost, "
          f"{len(mh['semantic_gap_remaining'])} left as a real vocabulary gap")
    lk = report["benchmark_leakage"]
    print(f"benchmark leakage: median overlap {lk['median_overlap']}  "
          f"max {lk['max_overlap']}  over 0.25: {len(lk['cases_over_0_25'])}")

    needs = report["literal_reachability"]["requires_expansion"]
    if needs:
        print(f"\nREQUIRES QUERY EXPANSION ({len(needs)}) -- no word the user typed "
              f"appears in the right agent's line, so the model must translate the "
              f"task into domain vocabulary before grepping:")
        print("  " + " ".join(needs))
        print("  Inspect one with ./scripts/eval_routing.py --explain <case>")

    if args.gate:
        failures = gate(report)
        if failures:
            print(f"\nFAILED: {len(failures)} routing threshold(s) breached.\n",
                  file=sys.stderr)
            for f in failures:
                print(f"  {f}", file=sys.stderr)
            return 1
        print("\nPASSED: all routing thresholds met.")

    if not args.ref:
        print(f"\nWrote {BASELINE.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
