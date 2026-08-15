#!/usr/bin/env python3
"""check_security.py -- enforce the claims SECURITY.md makes.

    ./scripts/check_security.py            # scan the corpus
    ./scripts/check_security.py --hosts    # also list every external host

SECURITY.md asserted four rules -- no credentials, no executable code in agent
markdown, reviewed shell scripts, report prompt injection -- and CI enforced
none of them. This makes the first two mechanical.

CALIBRATION IS THE HARD PART, NOT DETECTION

This corpus contains a security division whose job is to TEACH about secrets and
injection. It legitimately contains private-key headers, an AWS key prefix, a
burned OpenAI key used as a cautionary example, and the literal string "Ignore
all previous instructions" in an agent about adversarial prompt testing.

A scanner that flags those is not a strict scanner, it is a broken one: the
findings get waved through, and the next real secret is waved through with them.
So every allowlist entry in policy/security-allowlist.json names the file, the
matched text, and WHY it is legitimate -- and the entries are narrow (path plus
pattern), never a blanket path exemption.

If this ever reports more than a handful of allowlisted matches, tighten the
rule rather than widening the allowlist.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import REPO_ROOT, read_corpus  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

POLICY = REPO_ROOT / "policy" / "security-allowlist.json"

# severity: "error" fails the build, "advisory" is reported only.
RULES: dict[str, dict] = {
    "secret.aws_access_key": {
        "pattern": r"\bAKIA[0-9A-Z]{16}\b",
        "severity": "error",
        "why": "AWS access key id",
    },
    "secret.private_key": {
        "pattern": r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----",
        "severity": "error",
        "why": "private key material",
    },
    "secret.assignment": {
        "pattern": r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)"
                   r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
        "severity": "error",
        "why": "a credential assigned a long literal value",
    },
    "secret.openai_key": {
        "pattern": r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b",
        "severity": "error",
        "why": "OpenAI-style API key",
    },
    "exec.curl_pipe_shell": {
        "pattern": r"(?:curl|wget)[^\n|]{0,200}\|\s*(?:sudo\s+)?(?:ba|z|)sh\b",
        "severity": "error",
        "why": "pipes a download straight into a shell",
    },
    "exec.rm_rf_root": {
        "pattern": r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*\s+(?:/|~|\$HOME)\s*$",
        "severity": "error",
        "why": "recursive delete of a root or home path",
    },
    "injection.ignore_instructions": {
        "pattern": r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+"
                   r"(?:instructions|prompts|rules)",
        "severity": "error",
        "why": "prompt-injection phrasing",
    },
    "injection.reveal_prompt": {
        "pattern": r"(?i)\b(?:reveal|print|output|repeat)\s+(?:your\s+)?"
                   r"(?:system\s+prompt|instructions verbatim)",
        "severity": "error",
        "why": "attempts to extract the system prompt",
    },
    "exfil.credentials": {
        "pattern": r"(?i)\b(?:send|post|upload|exfiltrate)\b[^\n]{0,60}"
                   r"\b(?:\.env|credentials|secret|api[_-]?key)\b[^\n]{0,60}\b(?:to|http)",
        "severity": "error",
        "why": "sends credential material somewhere",
    },
}

HOST = re.compile(r"https?://([A-Za-z0-9.\-]+)")


def load_policy() -> dict:
    if not POLICY.exists():
        return {"allow": []}
    return json.loads(POLICY.read_bytes().decode("utf-8"))


def allowed(policy: dict, rule: str, path: str, text: str) -> str | None:
    """Return the justification if this exact match is allowlisted."""
    for entry in policy.get("allow", []):
        if entry["rule"] != rule or entry["path"] != path:
            continue
        if re.search(entry["match"], text):
            return entry["why"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hosts", action="store_true",
                    help="also list every external host referenced")
    ap.add_argument("--ref", help="git ref to scan (default: working tree)")
    args = ap.parse_args()

    policy = load_policy()
    corpus = read_corpus(args.ref)
    compiled = {k: re.compile(v["pattern"]) for k, v in RULES.items()}

    findings: list[tuple[str, str, str, str]] = []
    waived: list[tuple[str, str, str]] = []
    hosts: collections.Counter[str] = collections.Counter()

    for path in sorted(corpus):
        text = corpus[path].decode("utf-8", "replace")
        for host in HOST.findall(text):
            hosts[host.lower()] += 1
        for rule, rx in compiled.items():
            for m in rx.finditer(text):
                snippet = m.group(0)[:80]
                why = allowed(policy, rule, path, snippet)
                if why:
                    waived.append((rule, path, why))
                else:
                    findings.append((rule, path, snippet,
                                     RULES[rule]["severity"]))

    print(f"Scanned {len(corpus)} agents against {len(RULES)} rules")
    print(f"  allowlisted matches : {len(waived)}")
    print(f"  findings            : {len(findings)}")

    if waived:
        print("\nAllowlisted (each justified in policy/security-allowlist.json):")
        for rule, path, why in sorted(set(waived)):
            print(f"  {rule:32s} {path}")
            print(f"      {why}")

    if args.hosts:
        print(f"\nExternal hosts referenced: {len(hosts)}")
        for host, n in hosts.most_common():
            print(f"  {n:>4}  {host}")

    errors = [f for f in findings if f[3] == "error"]
    advisories = [f for f in findings if f[3] != "error"]

    if advisories:
        print(f"\nAdvisories ({len(advisories)}):")
        for rule, path, snippet, _ in advisories:
            print(f"  {rule}  {path}\n      {snippet!r}")

    if errors:
        print(f"\nFAILED: {len(errors)} security finding(s).\n", file=sys.stderr)
        for rule, path, snippet, _ in errors:
            print(f"  {rule}  ({RULES[rule]['why']})", file=sys.stderr)
            print(f"    {path}", file=sys.stderr)
            print(f"    {snippet!r}", file=sys.stderr)
        print("\nIf a finding is a legitimate teaching example, add a NARROW entry to",
              file=sys.stderr)
        print("policy/security-allowlist.json naming the file, the matched text and why.",
              file=sys.stderr)
        print("Never exempt a whole path: that turns the scanner off for that file",
              file=sys.stderr)
        print("permanently, including for a real secret added later.", file=sys.stderr)
        return 1

    print("\nPASSED: no unexplained secrets, injection phrasing or destructive "
          "commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
