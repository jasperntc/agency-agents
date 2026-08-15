# Using these agents in your projects

Three ways, depending on how much you want the project to control.

## 1. Link the repository (recommended)

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
