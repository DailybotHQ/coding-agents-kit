# Changelog

All notable changes to coding-agents-kit. Versions follow
[Semantic Versioning](https://semver.org); while the version is `0.x`, a
breaking change bumps the minor version **and** the interface version
reported by `ak doctor --json`.

## [0.1.0] — 2026-10-08

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

[0.1.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.1.0
