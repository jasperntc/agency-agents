#!/usr/bin/env bash
#
# check-runbooks.sh — enforce that strategy/runbooks.json stays in sync with the
# real agent roster.
#
# strategy/runbooks.json is the machine-readable roster for the NEXUS scenario
# runbooks: the Agency Agents app reads it to turn a runbook into a one-click
# team deploy, mapping each roster slug to a catalog agent. If a slug there
# doesn't resolve to a real agent, the app can't deploy that team — so this
# check fails the build when:
#   1. runbooks.json is not valid JSON, or an entry is missing a required field
#   2. any roster `agents[]` slug does not resolve to a real agent
#   3. any `doc` path does not exist
#   4. a runbook `slug` is duplicated
#
# RESOLVES AGAINST registry.json, not a filesystem glob.
#
# It previously derived the valid set by listing every tracked */*.md and
# subtracting a HARDCODED list of non-agent directories. That list went stale
# the moment the repository grew new top-level directories: docs/, metrics/,
# tests/ and schema/ were never added, so their markdown was counted as agents
# and the check accepted 277 slugs when only 270 were real. A runbook could
# reference "identity" or "homogenization" and pass.
#
# The registry contains exactly the agents, so the valid set is correct by
# construction and cannot rot again. Reading it needs no dependencies — it is
# JSON, and python3 is already required here.
#
# Slugs may be either the canonical `id` or the legacy filename stem; they are
# identical today, and accepting both means runbooks.json needs no migration.
#
# Usage: ./scripts/check-runbooks.sh

set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: python3 is required for the runbooks check." >&2
  exit 2
}

python3 - <<'PYEOF'
import json, os, sys

JSON = "strategy/runbooks.json"
REGISTRY = "registry.json"
errors = []

for path in (JSON, REGISTRY):
    if not os.path.isfile(path):
        print(f"ERROR {path} not found")
        sys.exit(1)

try:
    data = json.load(open(JSON, encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"ERROR {JSON} is not valid JSON: {e}"); sys.exit(1)

registry = json.load(open(REGISTRY, encoding="utf-8"))

# Accept the canonical id or the legacy filename stem. They are the same string
# today; accepting both means runbooks.json needs no migration, and a future
# rename that moves the stem keeps resolving through the id.
valid = set()
for agent in registry["agents"]:
    valid.add(agent["id"])
    valid.add(agent["legacy_ids"]["filename_stem"])

runbooks = data.get("runbooks")
if not isinstance(runbooks, list) or not runbooks:
    print(f"ERROR {JSON} has no 'runbooks' array"); sys.exit(1)

seen_slugs = set()
total_refs = 0
for rb in runbooks:
    rid = rb.get("slug", "<no slug>")
    for field in ("slug", "title", "mode", "doc", "roster"):
        if field not in rb:
            errors.append(f"runbook '{rid}' is missing required field \"{field}\"")
    if rb.get("slug") in seen_slugs:
        errors.append(f"duplicate runbook slug '{rb.get('slug')}'")
    seen_slugs.add(rb.get("slug"))
    doc = rb.get("doc")
    if doc and not os.path.isfile(doc):
        errors.append(f"runbook '{rid}': doc path does not exist: {doc}")
    for g in rb.get("roster", []):
        for slug in g.get("agents", []):
            total_refs += 1
            if slug not in valid:
                errors.append(f"runbook '{rid}' / group '{g.get('group','?')}': "
                              f"slug '{slug}' does not resolve to any agent in "
                              f"{REGISTRY}")

if errors:
    print(f"FAILED: {len(errors)} runbook consistency error(s). "
          f"strategy/runbooks.json must reference real agents.\n")
    for e in errors:
        print(f"  ERROR {e}")
    sys.exit(1)

print(f"PASSED: {len(runbooks)} runbooks, {total_refs} agent slug references — "
      f"all resolve against {len(registry['agents'])} registry agents.")
PYEOF
