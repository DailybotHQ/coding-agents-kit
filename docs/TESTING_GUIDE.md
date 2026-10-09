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
| permission posture (`--ask`, `--auto`, `AGENTKIT_PERMISSIONS`, `box_posture`) | `permissions` |
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

`harness-selftest` is internal: the `harness` scope runs it to prove the
runner reports failures correctly; never run it on its own.

## Scoped runs, consumers and fallback

Every command runs from the repository root with bash and python3 >= 3.9;
no other tool version changes flag behaviour.

- **Scoped invocation.** Name one or more scopes; there is no per-file or
  name filter, the scope *is* the unit. Examples from this repository:
  - `bash tests/run.sh oss` → ends `passed: 73  failed: 0  skipped: 0`
    (under a second).
  - `bash tests/run.sh dispatch profiles` → `passed: 226  failed: 0
    skipped: 0`.
  - `bash tests/run.sh run` → `passed: 67 …` (about 15 s; the slowest
    scope, it exercises timeouts).
  An unknown scope exits 2 with the list of valid scopes. Every run ends
  with the `guard` check, so a correct run always shows
  `ok   the real HOME gained no agentkit path or rc block`.
- **Lint.** `bash tests/run.sh lint` covers both languages. shellcheck can
  be scoped to files (`shellcheck -S warning lib/common.sh`); python
  checking is a project-wide compile of `lib/*.py`, so there is no
  scoped form for it. There is no formatter or type-checker.
- **Source-to-test mapping.** The scope map above is the rule: find the
  changed path in the left column and run its scopes.
- **Dependent consumers.** There is no affected-tests tool. `lib/common.py`,
  `lib/common.sh`, `lib/ak.py` and `bin/ak` are imported or run by every
  command, so a change there widens to the full suite. Any other
  `lib/*.py` module: `grep -n "import <module>\|from <module>" lib/*.py`
  lists its consumers; add their scopes.
- **Blind spots.** Kinds are data: a `providers.toml` change alters the
  argv of every launch even though no python changed, so it always runs
  `kinds`, `dispatch` and `permissions`. Templates in `lib/env.template`
  and the bundled skill are read at run time. The fakes in `tests/fakes/`
  emulate the vendor CLIs and can drift from the real CLIs; only the opt-in
  `live` scope sees a real CLI.
- **Escalation.** The full suite is mandatory for a change to the interface 1
  outputs (`ak doctor --json`, `ak env`, `ak run`), `docs/schema/`, the
  launcher (`bin/`, `lib/common.*`), `tests/run.sh` or `tests/lib.sh`, the
  CI workflows, and any release (`VERSION`).
- **Fallback.** When a scope cannot be derived with confidence, run
  `bash tests/run.sh`; it takes a few minutes (about four on a laptop,
  one to two in CI).

## Testing posture

- **Layers.** One layer, in `tests/scopes/<scope>.sh`. Each check drives
  the real launcher end to end inside a sandbox HOME, with fake CLIs at the
  vendor boundary. `tests/py/` holds helper checks that a scope calls. There
  is no separate unit tree, and the guide does not propose one.
- **Seams.** The tested seams are interface 1 (the JSON schema and exit
  codes), the argv each CLI receives, the environment each profile gets,
  and the files the installer and the hooks write. A change to a seam adds
  or updates a check in that seam's scope.
- **Fixtures.** Fixtures are deterministic: fakes record their input, and
  planted key values are visibly fake. Assertions name the observable
  behaviour (argv, file mode, an output line), never internal calls.

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
Every launch adds the CLI's autonomy flag by default, so a scope that pins
exact argv grammar calls `box_posture ask` after `box_new` (the box then runs
every command with `AGENTKIT_PERMISSIONS=ask`); the `permissions` scope owns
the default and the opt-out.
