# coding-agents-kit

One command surface for every terminal coding agent: `ak <kind> [@profile]`.

[![CI](https://github.com/DailybotHQ/coding-agents-kit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DailybotHQ/coding-agents-kit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/DailybotHQ/coding-agents-kit?sort=semver)](https://github.com/DailybotHQ/coding-agents-kit/releases)
[![License: MIT](https://img.shields.io/github/license/DailybotHQ/coding-agents-kit)](LICENSE)

## What it is

Every coding-agent CLI has its own flags for continuing a session, its own
way to keep a second account apart, its own headless mode and its own
"skip all permission prompts" switch. `ak` (also `agentkit`) puts one
grammar over all of them:

- **Kinds** — `claude`, `codex`, `cursor`, `opencode`, `pi`, `cline`,
  `grok`, `antigravity` (Google's `agy`), plus provider routes (`claude-glm`, `codex-azure`,
  `opencode-xai`, …). Kinds are data in [`providers.toml`](providers.toml).
- **Profiles** — several accounts per CLI (`ak claude @work`), each with its
  own login, sessions and provider keys.
- **The same session flags everywhere** — `-c`, `-r [id]`, `-l`, mapped to
  each CLI's own form.
- **Autonomy by default** — every launch adds the CLI's own autonomy flag;
  opt out with `--ask` or `AGENTKIT_PERMISSIONS=ask`. Autonomy is meant for
  disposable or sandboxed environments: on a host, opt out.
- **Interface 1 for other tools** — `ak run` (headless, one JSON result),
  `ak env` (a profile's environment), `ak doctor --json`.
- **Set it up with an agent** — the `agentkit-setup` skill and the read-only `ak setup probe | verify | docker`
  install, configure, verify and repair the kit on any host or container (pinned tag, verified tarball, keys by
  name only, consent before every change).
- **Quota of every account** — `ak usage` lists the 5-hour and weekly windows
  of each Claude, Codex and Z.AI account in one table (`--json` for tools),
  read-only, with `n/d` rows where no quota can be read; `ak pick` names the
  account with the most room for a kind.
- **Several agents, several accounts** — `ak pick --count N` plus `ak run`
  in one git worktree per delegate; the `agentkit-orchestrate` skill teaches
  an agent the loop.
- **Keys stay in one file** — provider keys never land in a config file.

Requirements: bash (macOS, Linux, WSL) or PowerShell (Windows), and
python3 ≥ 3.9. Nothing else.

## Install

```bash
git clone --branch v0.5.3 https://github.com/DailybotHQ/coding-agents-kit && ./coding-agents-kit/install.sh
```

Verify the checkout against the release's checksums (every shipped file is
listed):

```bash
cd coding-agents-kit
curl -fsSLO https://github.com/DailybotHQ/coding-agents-kit/releases/download/v0.5.3/SHA256SUMS
shasum -a 256 -c SHA256SUMS --ignore-missing      # Linux: sha256sum -c SHA256SUMS --ignore-missing
```

Windows: `.\coding-agents-kit\install.ps1`. Scripts and containers:
`./coding-agents-kit/install.sh --no-rc`. Details, upgrades and uninstall:
[docs/install.md](docs/install.md).

Let an agent do it: `npx --yes skills add DailybotHQ/coding-agents-kit@v0.5.3 --skill agentkit-setup`, then ask it
to set the kit up on this machine or to write a container recipe ([setup](docs/setup.md)).

## Quickstart

```bash
ak doctor                  # what is installed and configured
ak install codex           # a missing CLI, from its vendor, pinned
ak                         # list the kinds and which CLIs are installed
ak claude                  # Claude Code with its autonomy flag (the default)
ak codex -c                # continue the newest Codex session (codex resume --last)
ak claude @work -c         # a second Claude account, continue its newest session
ak claude-glm              # Claude Code routed to Z.AI GLM (key from ~/.config/agentkit/env)
ak claude --ask            # opt out for this launch: the CLI asks before acting
ak claude -- @src/app.ts   # `--` sends everything after it to the CLI untouched
ak usage                   # quota and usage of every account, one row each
ak run codex --cwd ~/src/api --timeout 900 --output-format json -- "fix the failing test"
```

### Several accounts

```bash
ak profiles add claude @work      # a second Claude account
ak claude @work                   # log in AS the profile (the first launch asks)
ak usage                          # every account's windows, read-only
ak pick claude                    # the Claude account with the most room
ak run claude @work --cwd ~/src/api --output-format json -- "fix the failing test"
```

A named profile reads its own keys (`ZAI_CODING_API_KEY_WORK` for
`claude-glm @work`) and never falls back to the default key. See
[Accounts](docs/accounts.md) and [Orchestration](docs/orchestration.md).

### Choosing accounts, and agents launching agents

```text
$ ak pick claude --count 2
claude @work2  headroom 100%  binding 5h  resets in 3h 48m
claude @work3  headroom 100%  binding 5h  resets in 3h 58m
```

```bash
ak pick claude --model fable --json      # pick-v1: chosen + every account with its reason
ak profiles --json                       # profiles-v1: every account by name, no values, no paths
ak run claude @work2 --cwd ../wt-api --trust-cwd --output-format json -- 'Implement the API lane; commit.'
```

`--trust-cwd` marks the lane's folder as trusted in that profile first, so a
new account does not stop at its folder-trust screen (opt-in only). A Claude
profile can also log in with its own token, `CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`
(from `claude setup-token`), for containers that reuse the host's accounts.
The loop — inventory, pick, one worktree per writer, failover, verify, merge
— is [Orchestration](docs/orchestration.md).

### Skills for agents

| Skill | For | Install |
| --- | --- | --- |
| `agentkit` | launching kinds, accounts, `ak run`, `ak usage`, `ak pick` (`ak --skill`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v0.5.3 --skill agentkit` |
| `agentkit-setup` | installing, configuring and repairing the kit (`ak --skill setup`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v0.5.3 --skill agentkit-setup` |
| `agentkit-orchestrate` | several agents over several accounts and vendors (`ak --skill orchestrate`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v0.5.3 --skill agentkit-orchestrate` |

### The grammar

The grammar is the same for every kind:

```
ak <kind> [@profile] [--ask | --auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
```

| Flag | claude | codex | cursor | opencode | pi | cline | grok | antigravity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `-c` | `--continue` | `resume --last` | `--continue` | `--continue` | `--continue` | newest session here → `--id <id>` | `--continue` | `--continue` |
| `-r <id>` | `--resume <id>` | `resume <id>` | `--resume=<id>` | `--session <id>` | `--session <id>` | `--id <id>` | `--resume <id>` | `--conversation <id>` |
| `-r` | `--resume` (picker) | `resume --all` | `--resume` | refused: run `opencode session list` | `--resume` | `history` | `--resume` | refused: no picker (`-r <conversation_id>` or `-c`) |
| `-l` | (passed through) | `resume --last` | `ls` | (passed through) | (passed through) | (passed through) | (passed through) | (passed through) |

Only the head of the arguments belongs to `ak`; the first token it does not
recognise, and everything after it, reaches the CLI unchanged. `ak`
replaces itself with the CLI (`exec`), so Herdr and your terminal see the
agent itself.

## How it fits with DeepWorkPlan

`ak` works on its own. In a repository that runs [DeepWorkPlan](https://deepworkplan.com),
the pack's `agentkit` addon uses `ak run` as the headless delegation transport
for a plan's `parallel_safe` tasks, and the lead assigns one account per lane
with `ak pick --count`; interactive lanes run in Herdr panes through
[herdr-peers](https://github.com/DailybotHQ/herdr-peers), started as
`ak <kind> @account --trust-cwd`. [devcontainer-kit](https://github.com/DailybotHQ/devcontainer-kit)
installs the kit, pinned and verified, in its images. The kit page is
[deepworkplan.com/kit/agentkit](https://deepworkplan.com/kit/agentkit).

## Part of the DeepWorkPlan ecosystem

[DeepWorkPlan](https://deepworkplan.com) turns any repository into an AI-first,
agent-pilotable codebase. These projects ship together; every addon is optional.

| Repository | Role | Purpose |
| --- | --- | --- |
| [deepworkplan-skill](https://github.com/DailybotHQ/deepworkplan-skill) | Pack | The methodology, specification and kit as an installable agent skill |
| [coding-agents-kit](https://github.com/DailybotHQ/coding-agents-kit) (this repository) | Addon: agentkit | One command for every coding agent: accounts, quota, `ak pick`, headless runs |
| [devcontainer-kit](https://github.com/DailybotHQ/devcontainer-kit) | Addon: devcontainer | A reproducible dev container per repository, wired to Herdr and the host's accounts |
| [herdr-peers](https://github.com/DailybotHQ/herdr-peers) | Addon: Herdr | Ask an agent in another Herdr pane, on any machine, and get one authorized reply |
| [deepworkplan-vim](https://github.com/DailybotHQ/deepworkplan-vim) | Addon: DeepWorkPlan Vim | The terminal editor for plans: plan browser, lanes view, Markdown viewer |
| [ai-diff-reviewer](https://github.com/DailybotHQ/ai-diff-reviewer) | Required local review | Reviews a change set locally and in CI; every Final Review runs it |
| [agent-skill](https://github.com/DailybotHQ/agent-skill) | Addon: Dailybot | The Dailybot agent skill: progress reports, check-ins, chat and more |
| [deepworkplan.com](https://deepworkplan.com) ([source](https://github.com/DailybotHQ/deepworkplan-website)) | Site and hub | The methodology, specification, kit catalog and `/init.md`; coordinates the ecosystem |

## Security

Autonomy by default with an always-effective opt-out (`--ask`,
`AGENTKIT_PERMISSIONS=ask`), keys only in `~/.config/agentkit/env` (mode 600),
no network except `ak install` fetching a pinned vendor installer you asked
for and `ak usage` / `ak pick` querying the usage endpoint of an account you run (one
request per account, read-only). Report vulnerabilities privately — see [SECURITY.md](SECURITY.md);
the threat model is [docs/SECURITY.md](docs/SECURITY.md).

## Documentation

- [Kinds and providers](docs/kinds.md) — the data model, provider keys, adding a kind
- [Accounts](docs/accounts.md) — the account model: per-CLI table, lifecycle, keys, macOS and Windows, troubleshooting
- [Profiles](docs/profiles.md) — accounts per CLI, keys per profile, Herdr hooks
- [Permissions](docs/permissions.md) — autonomy by default, the `--ask` opt-out, the `classic` and `providers` aliases
- [`ak run`](docs/run.md) — the headless contract, exit codes, the JSON envelope
- [Set up on any machine or container](docs/setup.md) — `ak setup`, the `agentkit-setup` skill, container recipes
- [`ak usage` and `ak pick`](docs/usage.md) — quota per account, reading the table, choosing an account ([usage-v1](docs/schema/usage-v1.json), [pick-v1](docs/schema/pick-v1.json))
- [Orchestration](docs/orchestration.md) — several agents over several accounts: worktrees, failover, Herdr, Deep Work Plans
- [`ak doctor` and `ak env`](docs/doctor.md) — interface 1 outputs ([schema](docs/schema/doctor-v1.json))
- [Install, `ak install`, aliases](docs/install.md)
- [Threat model](docs/SECURITY.md) · [Testing](docs/TESTING_GUIDE.md) · [Changelog](CHANGELOG.md)
- For agents: `ak --skill` prints the bundled skill (`ak --skill setup`, `ak --skill orchestrate` the others);
  install lines in [Skills for agents](#skills-for-agents).

## Contributing

Contributions are welcome: [CONTRIBUTING.md](CONTRIBUTING.md) (setup, the
test gate, commit and PR flow) and [AGENTS.md](AGENTS.md) for coding agents.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT — see [LICENSE](LICENSE). Credits in [CREDITS.md](CREDITS.md).

---

Part of the [DeepWorkPlan](https://deepworkplan.com) ecosystem — works on its own.
