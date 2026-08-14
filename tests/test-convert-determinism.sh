#!/usr/bin/env bash
#
# test-convert-determinism.sh -- conversion must be reproducible, and tools.json's
# renderer contract must be true.
#
# Two properties are checked:
#
#   1. DETERMINISM. The same source must produce byte-identical output on every
#      run and on every machine. Behavioural evaluation of a non-reproducible
#      artifact measures the build, not the skill -- you end up chasing eval
#      flake that is really conversion flake.
#
#   2. RENDERER EQUIVALENCE. tools.json states: "the same `format` name
#      guarantees byte-identical output, so two tools may share a format only if
#      their rendered files are identical." That is a contract with every
#      consumer (the Agency Agents app branches on `format` to decide which
#      renderer to use). It was asserted but never tested.
#
#      Only ONE format is shared between converted tools: skill-md, claimed by
#      both antigravity and osaurus. (`identity` is shared by claude-code and
#      copilot, but those install source files verbatim and have no converter.)
#      qwen-md and zcode-md are DISTINCT format names, so they are not bound by
#      the contract -- but convert_zcode's comment claims byte-identical output,
#      so that claim is checked separately and reported without failing.
#
# Usage: ./tests/test-convert-determinism.sh [--keep]
#
# Runs convert.sh twice into temp directories. Never writes to integrations/.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP=false
[[ "${1:-}" == "--keep" ]] && KEEP=true

WORK="$(mktemp -d)"
cleanup() { $KEEP || rm -rf "$WORK"; }
trap cleanup EXIT

failures=0
fail() { echo "FAIL  $*"; failures=$((failures + 1)); }
pass() { echo "ok    $*"; }

# hash_tree <dir> -- sorted "relpath  sha256" for every file, path-relative so
# two trees can be compared regardless of where they were built.
hash_tree() {
  local dir="$1"
  ( cd "$dir" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do
      printf '%s  %s\n' "${f#./}" "$(sha256sum "$f" | cut -d' ' -f1)"
    done )
}

echo "Converting (run 1)..."
"$REPO_ROOT/scripts/convert.sh" --out "$WORK/a" >/dev/null 2>&1
echo "Converting (run 2)..."
"$REPO_ROOT/scripts/convert.sh" --out "$WORK/b" >/dev/null 2>&1

# --- 1. determinism ---------------------------------------------------------

hash_tree "$WORK/a" > "$WORK/a.hashes"
hash_tree "$WORK/b" > "$WORK/b.hashes"

if diff -q "$WORK/a.hashes" "$WORK/b.hashes" >/dev/null; then
  pass "two runs are byte-identical ($(wc -l < "$WORK/a.hashes") files)"
else
  fail "two runs differ:"
  diff "$WORK/a.hashes" "$WORK/b.hashes" | head -20
fi

# --- 2. renderer equivalence: skill-md (CONTRACTUAL) ------------------------

# antigravity and osaurus both declare "format": "skill-md" in tools.json, so
# their rendered files must be identical. Both emit agency-<slug>/SKILL.md.
if [[ -d "$WORK/a/antigravity" && -d "$WORK/a/osaurus" ]]; then
  ag="$(cd "$WORK/a/antigravity" && find . -name SKILL.md | LC_ALL=C sort | while IFS= read -r f; do
          printf '%s  %s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"; done)"
  os="$(cd "$WORK/a/osaurus" && find . -name SKILL.md | LC_ALL=C sort | while IFS= read -r f; do
          printf '%s  %s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"; done)"
  if [[ "$ag" == "$os" ]]; then
    pass "skill-md: antigravity == osaurus ($(echo "$ag" | grep -c .) skills)"
  else
    fail "skill-md: antigravity and osaurus differ, but tools.json declares both"
    fail "      as format \"skill-md\", which promises byte-identical output."
    diff <(echo "$ag") <(echo "$os") | head -10
  fi
else
  fail "skill-md: antigravity or osaurus output missing"
fi

# --- 3. qwen vs zcode (INFORMATIONAL) ---------------------------------------

# Distinct format names, so not bound by the contract. convert_zcode's comment
# claims "Byte-identical to the qwen-md shape"; report whether that holds.
if [[ -d "$WORK/a/qwen/agents" && -d "$WORK/a/zcode/agents" ]]; then
  qw="$(cd "$WORK/a/qwen/agents" && find . -name '*.md' | LC_ALL=C sort | while IFS= read -r f; do
          printf '%s  %s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"; done)"
  zc="$(cd "$WORK/a/zcode/agents" && find . -name '*.md' | LC_ALL=C sort | while IFS= read -r f; do
          printf '%s  %s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"; done)"
  if [[ "$qw" == "$zc" ]]; then
    pass "qwen == zcode (informational; distinct format names in tools.json)"
  else
    echo "note  qwen and zcode differ. Not a contract breach -- they declare"
    echo "      different format names -- but convert_zcode's comment claims"
    echo "      byte-identical output, so the comment is wrong."
  fi
fi

# --- 4. no stray writes into the repo ---------------------------------------

if [[ -n "$(cd "$REPO_ROOT" && git status --porcelain integrations/ 2>/dev/null)" ]]; then
  fail "convert.sh with --out modified integrations/ in the repo"
else
  pass "integrations/ untouched (--out honoured)"
fi

echo
if (( failures > 0 )); then
  echo "FAILED: $failures check(s)."
  exit 1
fi
echo "PASSED"
