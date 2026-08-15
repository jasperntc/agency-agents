#!/usr/bin/env python3
"""build_plugins.py -- generate the Claude Code plugin marketplace.

    ./scripts/build_plugins.py            # generate
    ./scripts/build_plugins.py --check    # fail if stale

Produces one plugin per division so a project can link this repository and
enable only the specialists it needs:

    .claude-plugin/marketplace.json
    plugins/<division>/
        .claude-plugin/plugin.json
        agents/<id>.md
        README.md

WHY THIS OUTPUT IS COMMITTED

Everything under integrations/ is gitignored, because those conversions exist to
be run locally -- `convert.sh` is a convenience for the machine you are sitting
at, so committing its output would only bloat diffs.

A marketplace is the opposite. Claude Code fetches the plugin directory from the
repository, so files that are not committed do not exist as far as a consumer is
concerned. There is no field that points a plugin at content elsewhere; the
convention is `plugins/<name>/agents/`. Publishing IS the function.

So this output is committed and CI verifies it is current, exactly as
registry.json and conversion-manifest.json are. It is a published artifact, not
a local conversion, and the distinction is the reason the gitignore rule does
not apply.

WHY PER DIVISION

A project enabling `engineering@agency` gets 58 coherent specialists. Per-agent
plugins would match "install exactly what I need" more literally, but 270 plugin
directories is 540 extra files and a listing nobody can read. registry.json
stays the fine-grained catalogue for browsing.

Agent files are copied VERBATIM. install.sh --tool claude-code already installs
these same files unmodified into ~/.claude/agents/, so a plugin-delivered agent
and a locally installed one are byte-identical -- no second rendering to keep in
step.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.corpus import REPO_ROOT, dump_json  # noqa: E402

MARKETPLACE_NAME = "agency"
ROUTER = "router"

ROUTER_SKILL = """---
name: agency-router
description: >-
  Find and load the right Agency specialist for a task. Use when the work would
  benefit from a specialist perspective -- frontend, backend, security, GIS,
  marketing, finance, testing, game development, and more -- or when asked to
  pick an Agency agent. Searches {count} specialists across {divisions}
  divisions and loads only the one needed.
---

# Agency router

{count} specialists are available on disk. **Do not read them all.** Find the
right one, then load only that one.

## How to use this

1. **Search the index.** `index.md` in this skill directory has one line per
   specialist: `id | division | name | description`. Do not read the whole file;
   it is {index_kb}KB and reading it defeats the purpose.

   **Search distinctive phrases, not every word OR'd together.** Measured on
   this index, `app store|listing|conversion` returns 13 mostly irrelevant
   matches, while `app store` returns 2 and both are right. Generic words --
   conversion, optimization, strategy, performance, analysis -- appear in
   dozens of descriptions and drown the signal.

   ```
   Grep pattern="app store" path="index.md"          # good: distinctive
   Grep pattern="post-mortem|on-call" path="index.md" # good: domain jargon
   Grep pattern="strategy|analysis" path="index.md"   # bad: matches everything
   ```

   Start narrow. If nothing matches, widen one term at a time, or grep the
   division name when the domain is obvious (`| gis |`, `| security |`).

2. **Read the specialist.** Matching lines give you an `id`. Read
   `agents/<id>.md` in this skill directory. That file is the specialist's full
   instructions.

   **Check the description before committing to it.** The index describes what
   each specialist *claims*, in its own vocabulary, which may not be the
   vocabulary of the task. A task about React bundle size does not match
   "bundle" anywhere -- the frontend specialist's description says "performance
   optimization". If a grep returns something that looks wrong, it probably is;
   search a different term rather than using a poor match.

3. **Adopt its standards for the task**, while continuing to follow the user's
   actual request and any higher-priority instructions. A specialist is a lens,
   not a new set of orders.

## Choosing well

- Prefer **one** specialist. Two is reasonable when a task genuinely spans
  domains (a payments feature is backend *and* security). Beyond that you are
  diluting, not enriching.
- Match on the **problem**, not the vocabulary. A task mentioning "React" that
  is really about test strategy wants a testing specialist.
- If nothing matches well, say so and proceed normally. A poorly fitting
  specialist is worse than none -- it adds confident irrelevant detail.

## Why it works this way

Enabling every division as subagents would put ~{all_tokens:,} tokens of names
and descriptions into context before you type anything. Searching an index and
loading one file costs almost nothing until it is actually needed.

The division plugins (`engineering@agency`, `testing@agency`, ...) are the other
half of this: they register agents as real subagents you can delegate to in
parallel. Use those when you want delegation; use this when you want the right
perspective cheaply.
"""
PLUGINS_DIR = REPO_ROOT / "plugins"
MARKETPLACE_FILE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
REGISTRY = REPO_ROOT / "registry.json"

OWNER = {"name": "Jasper Ng", "url": "https://github.com/jasperntc/agency-agents"}


def plugin_readme(division: str, label: str, agents: list[dict]) -> str:
    rows = "\n".join(
        f"| `{a['id']}` | {a['name']} | {a['description']} |" for a in agents
    )
    return f"""# {label}

{len(agents)} specialists from [The Agency]({OWNER['url']}).

## Enable

Add to your project's `.claude/settings.json`:

```json
{{
  "extraKnownMarketplaces": {{
    "{MARKETPLACE_NAME}": {{
      "source": {{ "source": "github", "repo": "jasperntc/agency-agents" }}
    }}
  }},
  "enabledPlugins": {{ "{division}@{MARKETPLACE_NAME}": true }}
}}
```

## Agents

| id | name | description |
| --- | --- | --- |
{rows}

---
Generated by `scripts/build_plugins.py`. Do not edit by hand.
"""


def build(write: bool = True) -> dict:
    registry = json.loads(REGISTRY.read_bytes().decode("utf-8"))
    divisions = registry["divisions"]

    by_division: dict[str, list[dict]] = {}
    for agent in registry["agents"]:
        by_division.setdefault(agent["division"], []).append(agent)

    entries = []
    files: dict[str, bytes] = {}

    for division in sorted(by_division):
        agents = sorted(by_division[division], key=lambda a: a["id"])
        meta = divisions.get(division, {})
        label = meta.get("label", division)
        description = (f"{len(agents)} {label.lower()} specialists from The Agency: "
                       + ", ".join(a["name"] for a in agents[:6])
                       + (", and more." if len(agents) > 6 else "."))

        base = f"plugins/{division}"
        files[f"{base}/.claude-plugin/plugin.json"] = dump_json({
            "name": division,
            "description": description,
            "author": OWNER,
        })
        files[f"{base}/README.md"] = plugin_readme(division, label, agents).encode("utf-8")
        for agent in agents:
            files[f"{base}/agents/{agent['id']}.md"] = (
                (REPO_ROOT / agent["path"]).read_bytes()
            )

        entries.append({
            "name": division,
            "description": description,
            "author": OWNER,
            "category": division,
            "source": f"./{base}",
        })

    # --- the router: one plugin that searches all of them ---------------------
    #
    # Division plugins register agents as real subagents, which is powerful but
    # costs their full name+description listing in context whether used or not.
    # This plugin costs one skill description, searches an index, and loads a
    # single specialist on demand. The two are complementary: delegation versus
    # cheap perspective.
    #
    # It carries its own copy of the agent files because a consumer who enables
    # ONLY this plugin receives only this plugin's directory -- there is no way
    # to reference a sibling plugin's content. Disk is cheap; context is not.
    all_agents = sorted(registry["agents"], key=lambda a: a["id"])
    index_lines = [
        "# Specialist index",
        "",
        "One line per specialist: `id | division | name | description`.",
        "Grep this file. Do not read it whole.",
        "",
    ] + [
        f"{a['id']} | {a['division']} | {a['name']} | {a['description']}"
        for a in all_agents
    ]
    index_blob = ("\n".join(index_lines) + "\n").encode("utf-8")

    skill = ROUTER_SKILL.format(
        count=len(all_agents),
        divisions=len(by_division),
        index_kb=max(1, len(index_blob) // 1024),
        all_tokens=sum(len(a["name"]) + len(a["description"]) + 20
                       for a in all_agents) // 4,
    )

    rbase = f"plugins/{ROUTER}"
    files[f"{rbase}/.claude-plugin/plugin.json"] = dump_json({
        "name": ROUTER,
        "description": (f"Search {len(all_agents)} Agency specialists and load "
                        f"only the one a task needs. One skill instead of "
                        f"hundreds of subagent listings."),
        "author": OWNER,
    })
    files[f"{rbase}/skills/agency-router/SKILL.md"] = skill.encode("utf-8")
    files[f"{rbase}/skills/agency-router/index.md"] = index_blob
    for agent in all_agents:
        files[f"{rbase}/skills/agency-router/agents/{agent['id']}.md"] = (
            (REPO_ROOT / agent["path"]).read_bytes()
        )
    entries.insert(0, {
        "name": ROUTER,
        "description": (f"Search {len(all_agents)} Agency specialists and load "
                        f"only the one a task needs. Start here."),
        "author": OWNER,
        "category": "meta",
        "source": f"./{rbase}",
    })

    marketplace = {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": MARKETPLACE_NAME,
        "description": (f"{len(registry['agents'])} specialist AI agents across "
                        f"{len(entries)} divisions. One plugin per division; "
                        f"enable only what a project needs."),
        "owner": OWNER,
        "plugins": entries,
    }
    files[".claude-plugin/marketplace.json"] = dump_json(marketplace)

    if write:
        # Remove first so a deleted or renamed agent cannot leave an orphan
        # behind, the same reason convert.sh has clean_tool_output.
        if PLUGINS_DIR.exists():
            shutil.rmtree(PLUGINS_DIR)
        MARKETPLACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        for rel, blob in files.items():
            dest = REPO_ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)

    return {"files": files, "plugins": len(entries),
            "agents": sum(len(v) for v in by_division.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the committed output is current; exit 1 if stale")
    args = ap.parse_args()

    result = build(write=not args.check)
    files = result["files"]

    if args.check:
        stale = []
        for rel, blob in sorted(files.items()):
            path = REPO_ROOT / rel
            if not path.exists():
                stale.append(f"MISSING  {rel}")
            elif path.read_bytes() != blob:
                stale.append(f"STALE    {rel}")
        on_disk = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in list(PLUGINS_DIR.rglob("*")) + [MARKETPLACE_FILE]
            if p.is_file()
        }
        for rel in sorted(on_disk - set(files)):
            stale.append(f"ORPHAN   {rel}")

        if stale:
            print(f"FAILED: plugin output is stale ({len(stale)} file(s)).\n",
                  file=sys.stderr)
            for s in stale[:20]:
                print(f"  {s}", file=sys.stderr)
            if len(stale) > 20:
                print(f"  ... and {len(stale) - 20} more", file=sys.stderr)
            print("\nRegenerate with ./scripts/build_plugins.py", file=sys.stderr)
            return 1
        print(f"PASSED: {result['plugins']} plugins, {result['agents']} agents, "
              f"{len(files)} files current.")
        return 0

    print(f"Wrote {result['plugins']} plugins covering {result['agents']} agents "
          f"({len(files)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
