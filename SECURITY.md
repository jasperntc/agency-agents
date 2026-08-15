# Security Policy

## Reporting a Vulnerability

Do NOT open a public GitHub issue for security vulnerabilities. Open a private
security advisory via the GitHub Security tab.

- Acknowledgment: within 48 hours
- Initial assessment: within 7 days
- Fix or mitigation: depends on severity

## What is enforced, and by what

Every claim below maps to a job that runs in CI. Claims without a job are listed
separately as *not enforced*, because a policy nobody checks is documentation of
an intention, not a control.

| claim | enforced by | on |
| --- | --- | --- |
| No credentials in agent files | `scripts/check_security.py` | every PR, push to main |
| No prompt-injection phrasing | `scripts/check_security.py` | every PR, push to main |
| No destructive commands in agent files | `scripts/check_security.py` | every PR, push to main |
| Agent files are non-executable markdown | `scripts/lint-agents.sh` + schema | every PR, push to main |
| Shell scripts are statically analysed | `shellcheck --severity=error` | every PR, push to main |
| Generated output is not tampered with | `conversion_manifest.py --check` | every PR touching an input |
| The catalogue is not hand-edited | `build_registry.py --check` | every PR, push to main |
| Agent identity cannot silently change | `check-identity.py` | every PR, push to main |
| A change cannot degrade the agents it touches | `check_promotion.py` | every PR |
| A threshold cannot be loosened silently | `check_promotion.py` ratchet | every PR |

### Calibration is the point

This repository contains a security division whose job is to *teach* about
secrets and injection. It legitimately contains PEM headers, an AWS key prefix,
a deliberately burned OpenAI key used as a cautionary example, and the literal
string "Ignore all previous instructions" in an agent about adversarial prompt
testing.

A scanner that flags those is not strict, it is broken — findings get waved
through, and the next real secret gets waved through with them. So
`policy/security-allowlist.json` holds exactly **4 entries**, each naming the
rule, the file, a narrow regex for the matched text, and why it is legitimate.

Entries are never path-wide. Exempting a whole file turns the scanner off for it
permanently, including for a real secret added later. **If that list grows past
a handful, tighten the rule instead of widening the allowlist.**

Verified by negative control: a plausible AWS key, a live-looking API key, a
`curl | bash`, and an injection phrase each fail the build when added to any
agent.

## Threat model beyond the markdown

Agent files are non-executable prompts. The pipeline around them is not, and
that is where the real surface is.

### The Hermes plugin generates executable code

`scripts/build-hermes-plugin.py` emits a Python package — `__init__.py` plus a
3.9MB `agents.json` — which `install.sh --tool hermes` copies into
`~/.hermes/plugins/`. That code is generated from repository content and then
executed by Hermes.

Mitigations in place: the generated module is byte-reproducible and covered by
`metrics/conversion-manifest.json`, so an unexpected change to it fails CI;
`scripts/check-hermes-plugin.py` loads and exercises it on every run.

### The installer writes to user configuration

`install.sh` modifies files outside the repository:

- `ensure_hermes_plugin_enabled` rewrites `~/.hermes/config.yaml` with a
  hand-rolled YAML editor. It takes a timestamped backup first.
- `install_hermes` performs `rm -rf` on a destination directory. Two explicit
  basename guards refuse to run unless the path ends in `agency-agents-router`,
  so a mis-set `HERMES_PLUGIN_DIR` cannot delete a shared plugins directory.
- `ensure_converted` silently runs `convert.sh` when integration files are
  missing, with output discarded.
- `--link` symlinks repository files into user configuration, so a later
  `git pull` changes installed agent behaviour with no further consent step.

### The plugin marketplace is public

This repository is **public**, and `.claude-plugin/marketplace.json` is fetchable
by anyone who knows the URL. It is not listed in any directory, but *unlisted is
not private*.

Never put client work, credentials, or private context in an agent file. GitHub
does not permit converting a fork of a public repository to private; that
requires a separate repository.

## What is NOT enforced

Stated plainly, because the gap between what a policy claims and what it checks
is itself a risk:

- **Imported skills.** There is no quarantine pipeline yet. Anything pasted in
  from elsewhere gets the same scanning as first-party content and no more.
- **Behavioural safety.** Nothing evaluates whether an agent gives dangerous
  advice. The scanners are lexical; they see strings, not intent.
- **Dependency and supply chain.** No dependency scanning, and GitHub Actions
  are pinned to tags rather than commit SHAs.
- **Semantic injection.** The injection rules catch known phrasings. An
  instruction that subverts the model without using a known phrase will pass.
- **The install path itself.** `install.sh` is reviewed by humans, not by a
  test — it has no automated coverage.

## For contributors

- Never commit API keys, tokens, or credentials.
- Never add executable code inside agent markdown.
- Run `./scripts/check_security.py` before submitting. CI runs it anyway.
- If a legitimate teaching example trips a rule, add a narrow allowlist entry
  with a justification — do not exempt the file.
- Report suspicious agent definitions that attempt prompt injection.
