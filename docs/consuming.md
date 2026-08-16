# Using these agents in your projects

Three ways, depending on how much you want the project to control.

## 0. The router — start here

Enable one plugin and get all 270 specialists, searched on demand:

```json
{
  "extraKnownMarketplaces": {
    "agency": { "source": { "source": "github", "repo": "jasperntc/agency-agents" } }
  },
  "enabledPlugins": { "router@agency": true }
}
```

The router is a **skill**, not 270 subagents. It costs about 1,100 tokens of
instructions. When a task would benefit from a specialist, Claude greps a
compact index, reads the one matching agent, and adopts its standards.

Compare that with enabling divisions as subagents:

| approach | context cost before you type | delegation |
| --- | ---: | --- |
| `router@agency` | ~1,100 tokens | no — the specialist is read inline |
| `engineering@agency` | ~3,800 tokens (58 agents) | yes — real subagents |
| all 17 divisions | **~17,900 tokens** (270 agents) | yes |

They complement each other. Use the router when you want the right perspective
cheaply; use division plugins when you want to *delegate* to a subagent in
parallel. Enabling both is reasonable.

**Known limit, now measured.** The index describes each specialist in its own
vocabulary, which is not always the task's. On a 58-task benchmark, only **66%
of tasks share even one word** with the right specialist's index line — the
other third are reachable only if Claude first translates the request into the
field's terms ("second pair of eyes on this pull request" → `code review`). The
skill teaches that translation explicitly, and the numbers in it are the
measured ones. See [routing-evaluation.md](routing-evaluation.md).

## 1. Link the repository (division plugins)

Add to the project's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "agency": {
      "source": { "source": "github", "repo": "jasperntc/agency-agents" }
    }
  },
  "enabledPlugins": {
    "engineering@agency": true,
    "testing@agency": true
  }
}
```

That's it. No install step, no copied files. The project declares which divisions
it needs; Claude Code fetches them. `git pull` upstream and the project picks up
changes on its next marketplace update.

**One plugin per division**, 17 of them:

| plugin | agents | plugin | agents |
| --- | ---: | --- | ---: |
| `engineering` | 58 | `sales` | 9 |
| `specialized` | 57 | `testing` | 9 |
| `marketing` | 36 | `paid-media` | 7 |
| `game-development` | 21 | `project-management` | 7 |
| `gis` | 13 | `academic` | 6 |
| `security` | 12 | `spatial-computing` | 6 |
| `design` | 10 | `support` | 6 |
| `finance` | 5 | `product` | 5 |
| `healthcare` | 3 | | |

Enable only what a project needs. A project that pulls in `engineering` gets 58
specialists listed; pulling everything would be 270, which is more than any
project wants in context — OpenCode's runtime caps out around 119 for exactly
this reason.

To browse the full catalogue before choosing, read
[`registry.json`](../registry.json) — every agent with its id, division,
description and division counts.

### Why division-level rather than per-agent

Per-agent plugins would match "install exactly the three I need" more literally,
but that is 270 plugin directories, 540 extra files, and a marketplace listing
nobody can read. A division is the unit people actually think in.

## 2. Install into a project (no marketplace)

Works today, no plugin machinery:

```bash
# a per-project manifest: one agent id per line, # comments allowed
cat > .agency-agents <<'EOF'
engineering-frontend-developer
engineering-backend-architect
testing-reality-checker
EOF

/path/to/agency-agents/scripts/install.sh --link --no-interactive \
  --tool claude-code --path .claude/agents --agents-file .agency-agents
```

`--link` symlinks rather than copies, so `git pull` in the agency-agents clone
updates every project at once. `--agents-file` accepts ids or display names.

This is the finest-grained option — exactly the agents you list, nothing else —
and it works for all 16 supported tools, not just Claude Code. On Windows,
symlinks need developer mode; drop `--link` to copy instead.

## 3. Install user-wide

```bash
./scripts/install.sh --tool claude-code --division engineering,testing
```

Puts them in `~/.claude/agents/`, available in every project. Convenient, but
every project pays the context cost, so prefer 1 or 2.

## Which to choose

| | marketplace | `--agents-file` | user-wide |
| --- | --- | --- | --- |
| granularity | division | single agent | division |
| install step | none | one command | one command |
| updates | marketplace update | `git pull` (symlinked) | re-run install |
| works offline | after first fetch | yes | yes |
| other 15 tools | no | yes | yes |

## A note on visibility

This repository is **public**. The marketplace source above is a public GitHub
repo, so anyone who knows the URL can add it. It is not listed in any directory,
but unlisted is not private — do not put client work, credentials or private
context in an agent file.

GitHub does not allow converting a fork of a public repo to private; that would
require a separate repository, which also gives up the fork relationship and
easy upstream syncing.

## How the marketplace is built

`scripts/build_plugins.py` generates `.claude-plugin/marketplace.json` and the
`plugins/` tree from `registry.json`. Agent files are copied **verbatim**, so a
plugin-delivered agent and one installed by `install.sh --tool claude-code` are
byte-identical — there is no second rendering to keep in step.

The output is **committed**, unlike everything under `integrations/`. That is
deliberate: Claude Code fetches plugin directories from the repository, so
uncommitted files do not exist as far as a consumer is concerned. `integrations/`
is gitignored because it exists to be regenerated locally; here, publishing is
the function. CI verifies the committed copy is current, and regenerating is:

```bash
./scripts/build_plugins.py
```
