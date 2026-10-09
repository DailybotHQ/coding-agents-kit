# Review overrides for coding-agents-kit

coding-agents-kit is `ak` / `agentkit`: a bash launcher (`bin/ak`,
`lib/common.sh`) that sources the user's env file and exec's a python3
standard-library core (`lib/*.py`). The core turns the kinds model in
`providers.toml` (a TOML subset read by `lib/tomlmini.py`) into the argv and
environment of a vendor coding-agent CLI. It handles provider API keys and
writes into per-account profile directories, and other tools consume its
outputs as "interface 1". A good review here protects keys, the user's
files and that interface. Style matters much less.

## Severity overrides for this codebase

- **Always `critical`:** code that can print, log, write or embed the value
  of a `*_API_KEY` / `*_TOKEN` variable. That includes `ak env`
  (`lib/envcmd.py`), `ak doctor` (`lib/doctor.py`), error messages built
  from the environment, and files written by `lib/writers.py` or
  `lib/hooks.py`. A key may reach a child CLI only through its environment,
  via the `{key}` template (`docs/kinds.md`).
- **Always `critical`:** a write under a profile directory that can escape
  it. `lib/writers.py` `_atomic_write(..., confine=)` must keep the real
  path inside the profile, and `lib/hooks.py` must refuse symlinked
  destinations. Flag any new write path that skips them.
- **Always `critical`:** applying a permission-bypass flag (the `auto`
  fields in `providers.toml`, such as `--dangerously-skip-permissions`)
  without `--auto` or `AGENTKIT_PERMISSIONS=auto` (`lib/launch.py`).
  Pass-through is the default.
- **Always `critical`:** `subprocess` with `shell=True`, or string-built
  shell commands, fed by user, profile or env-file input. There are none
  today; keep it that way.
- **Escalate to `warning`:** any change to interface 1 that is not marked
  as breaking. This covers the `ak doctor --json` keys
  (`docs/schema/doctor-v1.json`), `ak env` output, the `ak run` envelope
  keys, and the exit codes in `lib/common.py` (`EXIT_OK` … `EXIT_INTERNAL`).
  A change needs an interface bump and a CHANGELOG entry.
- **Escalate to `warning`:** relaxing the env-file guard in
  `lib/common.sh`, which refuses a group- or world-writable file and exits
  70 from `bin/ak`.
- **Escalate to `warning`:** a non-standard-library import in `lib/`, or
  syntax newer than python 3.9 (CI runs 3.9).
- **Escalate to `warning`:** GNU-only or BSD-only tool flags in bash
  (`stat -c` vs `stat -f`, `sed -i`, `readlink -f`) without a fallback.

## Don't comment on

- Vendored skills under `.agents/skills/`. They are pinned in
  `skills-lock.json` and replaced on upgrade, never hand-edited.
- Plan state under `.dwp/`, except the tracked registry `.dwp/config.json`.
- Values in `tests/` that look like secrets but are visibly fake (`fake`,
  `test`, `planted`). Allowed fixtures are listed in `.public-hygiene-allow`.
- The vendor CLI flags in `providers.toml` themselves: they mirror each
  vendor's documented interface.
- Bash style already accepted by `shellcheck -S warning`.

## Repo-specific conventions

- **Kinds are data.** A new CLI, provider or route is a `providers.toml`
  entry plus a check, not a new code path in `lib/launch.py`.
- **Interface 1 is frozen** while its version is 1. Additive changes only.
  `bin/ak` and `bin/agentkit` must stay byte-identical.
- **Public repository.** No personal paths, private organisation or
  repository names, or non-public addresses. `scripts/check-public-hygiene.sh`
  enforces this in CI.
- **Pinned everything.** GitHub Actions are pinned by commit SHA, and
  vendor installers in `lib/installer.py` by version. No fetch-piped-to-shell
  line in `skills/agentkit/SKILL.md`.
- **Windows.** `install.ps1` and `win/*.cmd` mirror the POSIX installers.
  `lib/common.py` `windows_argv` resolves npm shims. A launcher change
  needs a matching Windows change, or a stated reason why not.

## Test-strategy expectations

- A behaviour change adds or updates a check in the matching
  `tests/scopes/<scope>.sh`, chosen from the scope map in
  `docs/TESTING_GUIDE.md`. A fixed bug gets a regression check.
- Checks drive the real launcher against the fakes in `tests/fakes/`
  inside a sandbox HOME. A test that reads the real HOME, the network or a
  real CLI outside the opt-in `live` scope is a `warning`.
- A secret-handling change plants a fake key value and asserts that it
  never appears in output or files (see `tests/scopes/security.sh`).
