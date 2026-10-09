# Changelog

All notable changes to coding-agents-kit are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is `0.x`, a breaking change bumps the minor version. The
interface version reported by `ak doctor --json` tracks the machine contract
only (the doctor JSON shape, `ak env`, the `ak run` grammar and envelope): it
changes when that contract breaks, not when behaviour such as the default
permission posture changes.

## [Unreleased]

## [0.2.2] - 2026-10-09

Interface stays **1**. Security fix to the 0.2.1 `ak env import` hardening.

### Fixed

- **`ak env import` could still import shell code** (a fix to the 0.2.1
  hardening): a single quote inside a double-quoted value ended the
  re-quoted word, so `Q="a'; touch x; '"` ran when the env file was next
  sourced. Values with a quote are refused in every form, a second guard
  refuses to write one, and the source path in the header comment is
  printable-only. A failed tarball swap now puts the previous version back.

## [0.2.1] - 2026-10-09

Interface stays **1**. Security fixes from the v0.2.0 review: the opt-out always wins.

### Fixed

- **An inherited opt-out could be lost.** A nested `ak` re-reads the env
  file, and an `AGENTKIT_PERMISSIONS=auto` line there (the v0.1 opt-in)
  replaced the `AGENTKIT_PERMISSIONS=ask` its parent passed on, so a
  sub-agent of an opted-out agent ran with autonomy. The inherited `ask`
  now outranks the file, in the bash launcher and the python core.
- **The opt-out now also wins over an explicit `--auto`**, so an alias or an
  agent that types `--auto` cannot bypass `AGENTKIT_PERMISSIONS=ask`.
- **`ak env import` imports plain data only.** Values a shell would
  interpret (`$(…)`, backquotes, `$`, `;`, `&`, `|`) were copied into the
  sourced env file; they are now skipped and reported, and imported values
  are written as single-quoted literals.
- **`ak install cursor` no longer replaces a foreign `~/.local/bin/agent`**
  (or `cursor-agent`): only a missing path or a link into the kit's own
  versions directory is replaced; anything else is left alone and reported.
  A reinstall keeps the previous tree until the new one is in place.

## [0.2.0] - 2026-10-09

Interface stays **1**. Autonomy by default (breaking behaviour), verified CLI installs, `ak env import`.

### Changed — breaking behaviour (interface stays 1)

- **Autonomy is the default.** Every launch (interactive, `ak run`, profiles,
  the `classic` preset and custom aliases) adds the CLI's own autonomy flag
  from `providers.toml`. Opt out with `--ask` on a launch or
  `AGENTKIT_PERMISSIONS=ask`; the opt-out always wins and is passed on to
  nested launches. `--ask` with `--auto` is a usage error. Autonomy is meant
  for disposable or sandboxed environments; `ak doctor` warns when it is on
  outside a container. The `classic` preset becomes plain name shortcuts for
  `ak <kind>`; custom aliases accept `--ask` or `--auto`. The doctor JSON
  shape is unchanged: `permissions` now reports `auto` when unset.
- **`ak install` verifies every CLI before anything runs.** Channels are
  `binary`, `tarball` and `npm`; every CLI is pinned to an exact version with
  a per-platform sha256 (claude from the vendor manifest; cursor and grok
  recorded on first use) or the npm registry `integrity`. A mismatch or an
  unpinned platform refuses the install and leaves nothing behind; archives
  are unpacked only when every entry stays inside its directory. Vendor
  install scripts are no longer run (the `script` channel and the
  `unpinned` key are retired). Cursor is pinned to `2026.10.01-e373342` and
  Grok to `1.0.50`, both previously unpinned. `scripts/update-pins.sh`
  re-derives every digest from its source.

### Added

- `ak env import <file>`: copies `KEY=value` lines from another env file
  into the kit's env file. It never overwrites a key and never prints a
  value, refuses a source others can write, skips shell code and empty
  values, keeps profile-suffixed keys, and keeps the destination mode 600.
- Public repository standard: `CONTRIBUTING.md`, `SECURITY.md` (policy),
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), issue and pull request
  templates, `CODEOWNERS`, Dependabot for GitHub Actions, `CLAUDE.md` →
  `AGENTS.md`.
- `scripts/check-public-hygiene.sh`: CI check that no tracked file carries
  private context or secret-shaped strings (allowlist for visibly fake
  fixtures in `.public-hygiene-allow`).
- Release workflow: an annotated `vX.Y.Z` tag publishes the GitHub release
  with the changelog section, the source tarball and `SHA256SUMS`.

### Changed

- README follows the ecosystem's standard section order; documentation
  examples use `$HOME` instead of a sample user path.

## [0.1.1] - 2026-10-08

Security release. **Interface 1** (unchanged). Upgrade from 0.1.0.

### Security

- **Profile writes could follow a symlink planted inside a profile**
  (medium; affects `0.1.0`). `ak profiles hooks`, and provider config
  writers when launching a profile, wrote through symlinks: a process able to
  write inside a profile directory (for example an agent running in it) could
  plant `<profile>/settings.json -> ~/.claude/settings.json` or a hook file
  pointing at a shell rc, and the next `ak profiles hooks` (or provider launch
  of that profile) wrote outside the profile. Hooks now refuse symlinked
  destinations and confine every write to the profile; provider writers
  confine writes to the profile when one is used (symlinks in the CLI's own
  home, e.g. a dotfiles-managed config, are still followed). Regression
  checks in the `security` test scope.
- Windows: programs that call ak must start the python core directly
  (`py -3 <install>\lib\ak.py …`), not `ak.cmd`, whose arguments `cmd.exe`
  re-parses; now stated in the skill and `docs/run.md`. The set of
  characters refused for batch-file targets now also covers `(`, `)` and
  line breaks.

Found by an independent review of the 0.1.0 release (the verification pass
of its pre-release fixes).

## [0.1.0] - 2026-10-08

First public release. **Interface 1.**

### Added

- `ak` / `agentkit`: one command surface for seven terminal coding agents —
  `claude`, `codex`, `cursor` (Cursor's `agent`, never Grok's), `opencode`,
  `pi`, `cline`, `grok` — and their provider variants `claude-glm`,
  `codex-{glm,azure,xai}`, `opencode-{glm,azure,xai}`, `pi-{glm,azure,xai}`,
  `cline-{azure,xai}`. Kinds are data in `providers.toml`.
- The same session flags everywhere (`-c`, `-r [id]`, `-l`) mapped to each
  CLI's own form; `--` passes everything through; `ak` exec's the CLI.
- Profiles: several accounts per CLI (`ak claude @work`), isolated per CLI
  under `~/.local/share/agentkit/profiles` (mode 700), per-profile provider
  keys `<KEY>_<SUFFIX>` with no fallback, and `ak profiles
  ls|add|path|run|rm|hooks`.
- Permissions posture: pass-through by default; `--auto` or
  `AGENTKIT_PERMISSIONS=auto` adds the CLI's own autonomy flag, never
  inherited by the agents a session starts.
- `ak run`: headless runs with a frozen per-CLI mapping, exit codes
  0/1/2/3/4/5/≥64, process-tree kill on timeout and cancellation, and one
  JSON envelope with `--output-format json`.
- `ak env`: a profile's environment as `KEY=VALUE` lines (no secrets) for
  launchers such as Herdr.
- `ak doctor [--json]`: CLIs, logins (file presence), profiles, key names,
  posture, aliases and Herdr hooks; JSON schema `docs/schema/doctor-v1.json`.
- `ak install`: missing CLIs from each vendor's official channel, pinned
  where the vendor allows it, never piped from the network into a shell.
- `ak alias` with a guarded shell rc block, and the `classic` preset
  (`claudex`, `codexx`, `cursorx`, `opencodex`, `pix`, `clinex`, `grokx` =
  `ak <kind> --auto`), **off** by default.
- `ak profiles hooks`: copies Herdr's agent-state hooks into a profile.
- Installers: `install.sh` (macOS, Linux, WSL; `--no-rc`, `--uninstall`)
  and `install.ps1` (Windows, native python core via `ak.cmd`).
- The `agentkit` skill (`skills/agentkit/SKILL.md`, printed by `ak --skill`).
- Test suite (`bash tests/run.sh`): sandbox HOME, fake CLIs, no network;
  CI on ubuntu, macOS, python 3.9 and Windows.

### Security

- Provider keys are never printed, logged or written by the kit; config
  writers store references only. Documented exception: Cline takes its key
  on the command line. See `docs/SECURITY.md`.
- A group- or world-writable env file is refused (it is sourced as shell).

### Credits

Redesigned from the author's earlier coding-agents-setup-kit (wrappers,
installers, provider writers) and profile work; see `CREDITS.md`.

[Unreleased]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.2
[0.2.1]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.1
[0.2.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.0
[0.1.1]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.1.1
[0.1.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.1.0
