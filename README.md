<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/DailybotHQ/coding-agents-kit/main/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/DailybotHQ/coding-agents-kit/main/assets/logo-light.png">
    <img alt="Coding Agents Kit" src="https://raw.githubusercontent.com/DailybotHQ/coding-agents-kit/main/assets/logo-light.png" width="440">
  </picture>
</p>

# coding-agents-kit

**One command for every terminal coding agent:** `ak <kind> [@profile]` — install, launch, switch accounts and read every account's quota, the same way for all of them.

[![CI](https://github.com/DailybotHQ/coding-agents-kit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DailybotHQ/coding-agents-kit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/DailybotHQ/coding-agents-kit?sort=semver)](https://github.com/DailybotHQ/coding-agents-kit/releases)
[![License: MIT](https://img.shields.io/github/license/DailybotHQ/coding-agents-kit)](LICENSE)
![Agents: 8](https://img.shields.io/badge/coding%20agents-8-0A3CF5)
![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows%20%C2%B7%20containers-1F2328)
![Dependencies](https://img.shields.io/badge/dependencies-bash%20%2B%20python3%20stdlib-1F2328)

<p align="center">
  <a href="#supported-coding-agents">Supported agents</a> ·
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#several-accounts">Several accounts</a> ·
  <a href="docs/usage.md">Quota</a> ·
  <a href="docs/orchestration.md">Orchestration</a> ·
  <a href="#documentation">Docs</a>
</p>

```text
$ ak usage
  PROFILE   PLAN    WINDOW                 USED             RESET

claude · Claude Code
  @work     max     5-hour                 ██▊░░░░░░░  27%  in 1h 15m
                    7-day all models       ███▊░░░░░░  38%  in 1d 22h
  @team     team    5-hour                 ▋░░░░░░░░░   6%  in 3h 55m

codex
  @work     team    5-hour                 ████████▍░  84%  in 26m
                    7-day                  ██▌░░░░░░░  25%  in 5d 16h

antigravity · Antigravity CLI
  @default  AI Pro  5-hour Gemini          ███▍░░░░░░  34%  in 1h 10m
                    7-day Claude and GPT   ░░░░░░░░░░   0%  in 7d 0h
  @work     AI Pro  5-hour Gemini          ▏░░░░░░░░░   1%  in 3h 55m

cursor · Cursor Agent
  @default  -       n/d                    logged in: web session only
```

## What it is

Every coding-agent CLI has its own flags for continuing a session, its own
way to keep a second account apart, its own headless mode and its own
"skip all permission prompts" switch. `ak` (also `agentkit`) puts **one
grammar** over all of them, so people, scripts and other agents drive any CLI
— with any of your accounts — without learning its quirks.

### Supported coding agents

| Agent | Command | `ak` kind | Several accounts (`@profile`) | Quota in `ak usage` |
| --- | --- | --- | --- | --- |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | `claude` | `claude` | yes — its own config dir | 5-hour and weekly windows, per model |
| [Codex](https://developers.openai.com/codex/cli) | `codex` | `codex` | yes — its own `CODEX_HOME` | 5-hour and weekly windows, resets held |
| [Cursor Agent](https://cursor.com/docs/cli) | `agent` | `cursor` | yes — its own home and credential store | connected only (web session) |
| [OpenCode](https://opencode.ai/docs) | `opencode` | `opencode` | yes — its own XDG dirs | through the provider key |
| [Pi](https://github.com/earendil-works/pi) | `pi` | `pi` | yes — its own agent dir | through the provider key |
| [Cline](https://docs.cline.bot) | `cline` | `cline` | yes — its own `CLINE_DIR` | through the provider key |
| [Grok](https://x.ai/cli) | `grok` | `grok` | yes — its own `GROK_HOME` | connected only (per-session usage) |
| [Antigravity CLI](https://antigravity.google/docs/cli) | `agy` | `antigravity` | yes — its own home (one Google login each on Linux and in containers) | Gemini and Claude/GPT, 5-hour and weekly |

`ak install <kind>` installs each one from its vendor, **pinned to an exact
version and verified** (sha256 or npm integrity). Kinds are data in
[`providers.toml`](providers.toml): adding an agent is a table, not code.

### Provider routes

The same CLIs, routed to another model provider with one key per account:

| Provider | Key | Kinds | Quota |
| --- | --- | --- | --- |
| Z.AI GLM Coding Plan | `ZAI_CODING_API_KEY[_SUFFIX]` | `claude-glm`, `codex-glm`, `opencode-glm`, `pi-glm` | 5-hour and weekly credits |
| Azure OpenAI / Microsoft Foundry | `AZURE_OPENAI_API_KEY[_SUFFIX]` | `codex-azure`, `opencode-azure`, `pi-azure`, `cline-azure` | in the Azure portal |
| xAI | `XAI_API_KEY[_SUFFIX]` | `codex-xai`, `opencode-xai`, `pi-xai`, `cline-xai`, `grok` | needs a management key |
| Gemini API | `GEMINI_API_KEY[_SUFFIX]` | `antigravity` | in Google AI Studio |

### What you get

| | |
| --- | --- |
| **One grammar** | `-c`, `-r [id]`, `-l` mean the same in every CLI; `ak` maps them to each one's own form ([the grammar](#the-grammar)). |
| **Several accounts** | `ak claude @work`, `ak codex @client-x`: each profile has its own login, sessions, settings and keys, side by side. |
| **Quota of every account** | `ak usage` (or `ak status`) lists every account of every CLI in one table, `ak pick` names the one with the most room, `ak capacity` judges one. |
| **Headless runs** | `ak run` runs any kind non-interactively and returns one JSON result — the transport other tools and agents use. |
| **Agents launching agents** | `ak pick --count N`, leases and the `agentkit-orchestrate` skill spread lanes over accounts and vendors. |
| **Autonomy by default** | each CLI's own autonomy flag on every launch, with an opt-out that always wins: `--ask` or `AGENTKIT_PERMISSIONS=ask`. Meant for disposable or sandboxed environments. |
| **Keys stay in one file** | `~/.config/agentkit/env` (mode 600); no key lands in a config file, a log or an output. |
| **Set up by an agent** | the `agentkit-setup` skill and the read-only `ak setup probe \| verify \| docker` install and repair the kit on any host or container. |
| **Interface 1 for tools** | `ak run`, `ak env`, `ak doctor --json`, with versioned JSON schemas. |

Requirements: bash (macOS, Linux, WSL) or PowerShell (Windows), and
python3 ≥ 3.9. Nothing else.

## Install

```bash
git clone --branch v1.2.0 https://github.com/DailybotHQ/coding-agents-kit && ./coding-agents-kit/install.sh
```

Verify the checkout against the release's checksums (every shipped file is
listed):

```bash
cd coding-agents-kit
curl -fsSLO https://github.com/DailybotHQ/coding-agents-kit/releases/download/v1.2.0/SHA256SUMS
shasum -a 256 -c SHA256SUMS --ignore-missing      # Linux: sha256sum -c SHA256SUMS --ignore-missing
```

Windows: `.\coding-agents-kit\install.ps1`. Scripts and containers:
`./coding-agents-kit/install.sh --no-rc`. Details, upgrades and uninstall:
[docs/install.md](docs/install.md).

Let an agent do it: `npx --yes skills add DailybotHQ/coding-agents-kit@v1.2.0 --skill agentkit-setup`, then ask it
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
ak capacity claude @work          # one account: ok | low | critical | unknown
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

Long runs stay ahead of their limits: an agent asks for its own room at each
task boundary and hands off before it runs dry, and leads lease the accounts
they hand out so two never share one Codex login:

```bash
ak capacity --self --json                        # capacity-v1, from a cache of usage numbers (ak usage stays live)
ak lease codex @work1 --owner local:w1:p2        # advisory; Codex takes one holder
ak pick codex --owner local:w1:p1 --count 2      # spreads lanes: every active lease counts, yours too
```

### Skills for agents

| Skill | For | Install |
| --- | --- | --- |
| `agentkit` | launching kinds, accounts, `ak run`, `ak usage`, `ak pick` (`ak --skill`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v1.2.0 --skill agentkit` |
| `agentkit-setup` | installing, configuring and repairing the kit (`ak --skill setup`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v1.2.0 --skill agentkit-setup` |
| `agentkit-orchestrate` | several agents over several accounts and vendors (`ak --skill orchestrate`) | `npx --yes skills add DailybotHQ/coding-agents-kit@v1.2.0 --skill agentkit-orchestrate` |

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
Inside a Herdr pane, `ak` also makes Herdr restore the pane after a restart
as `ak <kind> @<profile> --resume <id>` — the same account, key and posture —
instead of the bare CLI ([Profiles → Resuming after a Herdr restart](docs/profiles.md#resuming-after-a-herdr-restart)).
In any other terminal, `ak last` relaunches the last `ak <kind> @<profile>` of
the current directory with `-c` (`-r` for the picker, `ak last ls` for the list).

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
- [`ak usage`, `ak pick`, `ak capacity` and `ak lease`](docs/usage.md) — quota per account, reading the table, choosing an account, one account's room, the usage cache, leases ([usage-v1](docs/schema/usage-v1.json), [pick-v1](docs/schema/pick-v1.json), [capacity-v1](docs/schema/capacity-v1.json), [leases-v1](docs/schema/leases-v1.json))
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
