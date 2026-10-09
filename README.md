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
  `grok`, plus provider routes (`claude-glm`, `codex-azure`,
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
- **Keys stay in one file** — provider keys never land in a config file.

Requirements: bash (macOS, Linux, WSL) or PowerShell (Windows), and
python3 ≥ 3.9. Nothing else.

## Install

```bash
git clone --branch v0.3.0 https://github.com/DailybotHQ/coding-agents-kit && ./coding-agents-kit/install.sh
```

Windows: `.\coding-agents-kit\install.ps1`. Scripts and containers:
`./coding-agents-kit/install.sh --no-rc`. Details, upgrades and uninstall:
[docs/install.md](docs/install.md).

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
ak run codex --cwd ~/src/api --timeout 900 --output-format json -- "fix the failing test"
```

The grammar is the same for every kind:

```
ak <kind> [@profile] [--ask | --auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
```

| Flag | claude | codex | cursor | opencode | pi | cline | grok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `-c` | `--continue` | `resume --last` | `--continue` | `--continue` | `--continue` | newest session here → `--id <id>` | `--continue` |
| `-r <id>` | `--resume <id>` | `resume <id>` | `--resume=<id>` | `--session <id>` | `--session <id>` | `--id <id>` | `--resume <id>` |
| `-r` | `--resume` (picker) | `resume --all` | `--resume` | refused: run `opencode session list` | `--resume` | `history` | `--resume` |
| `-l` | (passed through) | `resume --last` | `ls` | (passed through) | (passed through) | (passed through) | (passed through) |

Only the head of the arguments belongs to `ak`; the first token it does not
recognise, and everything after it, reaches the CLI unchanged. `ak`
replaces itself with the CLI (`exec`), so Herdr and your terminal see the
agent itself.

## Documentation

- [Kinds and providers](docs/kinds.md) — the data model, provider keys, adding a kind
- [Profiles](docs/profiles.md) — accounts per CLI, keys per profile, Herdr hooks
- [Permissions](docs/permissions.md) — autonomy by default, the `--ask` opt-out, the `classic` and `providers` aliases
- [`ak run`](docs/run.md) — the headless contract, exit codes, the JSON envelope
- [`ak doctor` and `ak env`](docs/doctor.md) — interface 1 outputs ([schema](docs/schema/doctor-v1.json))
- [Install, `ak install`, aliases](docs/install.md)
- [Threat model](docs/SECURITY.md) · [Testing](docs/TESTING_GUIDE.md) · [Changelog](CHANGELOG.md)
- For agents: `ak --skill` prints the bundled skill; install it with
  `npx --yes skills add DailybotHQ/coding-agents-kit@v0.3.0 --skill agentkit`.

## Security

Autonomy by default with an always-effective opt-out (`--ask`,
`AGENTKIT_PERMISSIONS=ask`), keys only in `~/.config/agentkit/env` (mode 600),
no network except `ak install` fetching a pinned vendor installer you asked
for. Report vulnerabilities privately — see [SECURITY.md](SECURITY.md);
the threat model is [docs/SECURITY.md](docs/SECURITY.md).

## Contributing

Contributions are welcome: [CONTRIBUTING.md](CONTRIBUTING.md) (setup, the
test gate, commit and PR flow) and [AGENTS.md](AGENTS.md) for coding agents.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT — see [LICENSE](LICENSE). Credits in [CREDITS.md](CREDITS.md).

---

Part of the [DeepWorkPlan](https://deepworkplan.com) ecosystem — works on its own.
