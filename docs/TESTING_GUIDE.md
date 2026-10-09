# Testing guide

One entry point: `bash tests/run.sh [scope...]`. With no scope it runs every
scope except `live`. It prints one line per check (`ok   …`, `FAIL …`,
`skip …`) and ends with `passed: N  failed: N  skipped: N`; it exits 0 only
when nothing failed.

## What the suite guarantees

- **Sandbox HOME.** The runner exports `HOME` to a fresh directory under
  `$TMPDIR` before anything runs, and every command the checks start runs
  under `env -i` with that HOME. A final `guard` check proves the real HOME
  gained no `~/.local/share/agentkit`, `~/.config/agentkit` or rc block.
- **Fakes, never real CLIs.** `tests/fakes/{claude,codex,agent,opencode,pi,cline,grok}`
  record their argv (one `ARG=` line per argument, boundaries kept), working
  directory and the isolation variables, and can emulate each CLI's headless
  JSON shape (`FAKE_MODE=headless`). Their knobs are documented at the top of
  `tests/fakes/_fake.sh`. The suite's `PATH` is the box's fakes, a link to the
  python3 under test, and `/usr/bin:/bin` — never Homebrew or `~/.local/bin`.
- **No network, no installs.** Installer checks run with fake `curl`/`npm`.
- **No secret values.** Checks plant fake key values and assert they never
  appear in kit output or files; fakes print `(set)` for secret variables
  unless a key-routing check asks for the value.

## Scope map

| Surface you touched | Scope(s) to run |
| --- | --- |
| `tests/` (runner, fakes, helpers) | `harness`, `lint` |
| `providers.toml`, `lib/kinds.py`, `lib/writers.py`, `lib/tomlmini.py` | `kinds`, `dispatch`, `permissions` |
| `bin/ak`, `bin/agentkit`, `lib/common.sh`, `lib/ak.py`, `lib/launch.py`, `lib/common.py` | `dispatch`, `permissions`, `profiles` |
| `lib/profiles.py` | `profiles` (+ `doctor`, `run`) |
| permission posture (`--auto`, `AGENTKIT_PERMISSIONS`) | `permissions` |
| `ak env` (`lib/envcmd.py`), `ak doctor` (`lib/doctor.py`), `docs/schema/doctor-v1.json` | `doctor` |
| `ak run` (`lib/run.py`) | `run` |
| `install.sh`, `install.ps1`, `win/`, `lib/env.template`, `ak install` (`lib/installer.py`) | `install` |
| `ak alias` (`lib/aliases.py`), the rc block, the `classic` preset | `aliases` |
| `skills/agentkit/` | `skill` |
| `ak profiles hooks` (`lib/hooks.py`) | `hooks` |
| anything that prints, logs or writes | `security` |
| the frozen interface (grammar, env prefix, outputs) | `contract` |
| `scripts/check-public-hygiene.sh`, `.public-hygiene-allow`, any tracked file | `hygiene` (and the CI job `public hygiene`: `bash scripts/check-public-hygiene.sh`) |
| repository meta (README sections, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, `.github/`, release workflow) | `oss` |
| a shared module or several surfaces | the full suite |

`live` runs a real CLI and is never part of the default run: it reports
`unavailable` unless `AGENTKIT_TEST_LIVE=1` is set, because a real CLI reads
your real login and writes sessions into your real HOME.

## Interpreters and tools

- `AK_TEST_PYTHON=/path/to/python3` runs the suite under another interpreter.
  The kit supports python3 >= 3.9; `lint` compiles `lib/*.py` with a 3.9 when
  one is on the machine, and CI runs the whole suite under 3.9.
- `shellcheck` is used when installed (`lint` reports `skip` otherwise); the
  release gate requires it: `shellcheck -S warning bin/* lib/*.sh install.sh tests/run.sh`.

## CI

`.github/workflows/ci.yml` runs the full suite on ubuntu and macOS, again
under python 3.9, and a Windows job that parses every PowerShell file and runs
the python core natively (`ak --version`, `ak doctor --json`).

## Writing a check

Add it to the scope file in `tests/scopes/<scope>.sh` (a function named
`scope_<scope>`), using the helpers in `tests/lib.sh`: `box_new` for an
isolated world, `ak` / `ak_split` to run the kit inside it, and
`check` / `expect_eq` / `expect_line` / `expect_has` / `expect_lacks`.
