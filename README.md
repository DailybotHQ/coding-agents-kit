# coding-agents-kit

Install and launch every terminal coding agent with one command surface: `ak <kind> [@profile]`. Canonical kinds (claude, codex, cursor, opencode, pi, cline, grok) plus provider variants (glm, azure, xai), multiple accounts per CLI through profiles, the same session flags everywhere, headless runs (`ak run`) and a doctor. Pass-through by default; autonomy is an explicit opt-in. API keys never land in config files.

> **v0.1.0 — interface 1.** Part of the [DeepWorkPlan](https://deepworkplan.com) ecosystem, and fully usable without it.

## Why

Every coding-agent CLI has its own flags for continuing a session, its own
way to keep a second account apart, its own headless mode and its own
"skip all permission prompts" switch. `ak` puts one grammar over all of
them, keeps accounts and provider keys separate, and never turns autonomy
on behind your back.

## Install

```bash
git clone --branch v0.1.0 https://github.com/DailybotHQ/coding-agents-kit && ./coding-agents-kit/install.sh
ak doctor            # what is installed and configured
ak install codex     # a missing CLI, from its vendor, pinned
```

Windows: `.\coding-agents-kit\install.ps1`. Needs bash (macOS/Linux) and
python3 ≥ 3.9; nothing else. `--no-rc` for scripts and containers. Details:
[install](docs/install.md).

## Usage

```bash
ak                         # list the kinds and which CLIs are installed
ak claude                  # Claude Code, exactly as `claude` (no flags added)
ak codex -c                # continue the newest Codex session (codex resume --last)
ak cursor -r <id>          # resume a Cursor chat by id
ak claude-glm              # Claude Code routed to Z.AI GLM (key from the env file)
ak claude @work -c         # a second Claude account, continue its newest session
ak claude --auto           # opt in to the CLI's own autonomy flag for this launch
ak claude -- @src/app.ts   # `--` sends everything after it to the CLI untouched
```

The grammar is the same for every kind:

```
ak <kind> [@profile] [--auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
```

| Flag | claude | codex | cursor | opencode | pi | cline | grok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `-c` | `--continue` | `resume --last` | `--continue` | `--continue` | `--continue` | newest session here → `--id <id>` | `--continue` |
| `-r <id>` | `--resume <id>` | `resume <id>` | `--resume=<id>` | `--session <id>` | `--session <id>` | `--id <id>` | `--resume <id>` |
| `-r` | `--resume` (picker) | `resume --all` | `--resume` | refused: run `opencode session list` | `--resume` | `history` | `--resume` |
| `-l` | (passed through) | `resume --last` | `ls` | (passed through) | (passed through) | (passed through) | (passed through) |

Only the head of the arguments belongs to `ak`: the first token it does not
recognise, and everything after it, reaches the CLI unchanged. `ak` replaces
itself with the CLI (`exec`), so Herdr and your terminal see the agent itself.

More: [kinds and providers](docs/kinds.md) · [profiles](docs/profiles.md) · [permissions](docs/permissions.md) · [`ak run`](docs/run.md) · [`ak doctor` / `ak env`](docs/doctor.md) · [install and aliases](docs/install.md) · [testing](docs/TESTING_GUIDE.md).

## Headless, env and doctor (interface 1)

```bash
ak run codex --cwd ~/src/api --timeout 900 --output-format json -- "fix the failing test"
ak env claude @work        # KEY=VALUE lines for another launcher (Herdr), never a secret
ak doctor --json           # {"interface": 1, "kinds": …, "profiles": …, "keys": [names only], …}
```

`ak run` exits 0 success · 1 agent failure · 2 usage · 3 not installed / not
logged in / key or profile missing · 4 timeout · 5 cancelled; with
`--output-format json` stdout is exactly one JSON object. See
[`ak run`](docs/run.md) and [`ak doctor` / `ak env`](docs/doctor.md).

## Security model

- **Pass-through by default.** No permission-bypass flag is ever added
  unless you pass `--auto` or set `AGENTKIT_PERMISSIONS=auto`; agents started
  by an agent do not inherit it. The `classic` aliases (`claudex`, …) ship off.
- **Keys stay where you put them:** `~/.config/agentkit/env` (mode 600; a
  file others can write is refused). The kit prints and writes variable
  names only; provider configs reference keys (`env_key`, `{env:KEY}`,
  `"$KEY"`). Cline's key on its command line is the one documented exception.
- **No surprises on your machine:** one guarded rc block (`--no-rc` to
  skip), no network except `ak install` fetching a pinned vendor installer
  you asked for, never piped into a shell.

Full threat model: [SECURITY](docs/SECURITY.md).

## For agents

`ak --skill` prints the bundled skill; install it into an agent with
`npx --yes skills add DailybotHQ/coding-agents-kit@v0.1.0 --skill agentkit`.

## License

MIT — see [LICENSE](LICENSE). Credits in [CREDITS.md](CREDITS.md).
