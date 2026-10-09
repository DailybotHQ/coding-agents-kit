# AGENTS.md — coding-agents-kit

Entry point for AI agents working **on** this repository.

## Purpose

Install and launch every terminal coding agent with one command surface: `ak <kind> [@profile]`. Canonical kinds (claude, codex, cursor, opencode, pi, cline, grok) plus provider variants (glm, azure, xai), multiple accounts per CLI through profiles, the same session flags everywhere, headless runs (`ak run`) and a doctor. Pass-through by default; autonomy is an explicit opt-in. API keys never land in config files.

## Command / skill

agentkit (alias ak); skill agentkit

## Layout

| Path | What |
| --- | --- |
| `bin/ak`, `bin/agentkit` | one byte-identical bash launcher: sources the env file, exec's the python core |
| `lib/ak.py` + `lib/*.py` | the python3 stdlib core: `launch` (dispatcher), `kinds` (+ `tomlmini`, `writers`), `profiles`, `run`, `envcmd`, `doctor`, `aliases`, `installer`, `hooks`, `common` |
| `lib/common.sh`, `lib/env.template` | the launcher's shell half; the env file template |
| `providers.toml` | the kinds model as data (CLIs, providers, kinds) — see `docs/kinds.md` |
| `skills/agentkit/SKILL.md` | the bundled skill (`ak --skill`) |
| `install.sh`, `install.ps1`, `win/*.cmd` | installers (POSIX, Windows) and Windows shims |
| `tests/run.sh`, `tests/scopes/`, `tests/fakes/`, `tests/py/` | the suite: sandbox HOME, fake CLIs, one scope per surface |
| `docs/` | user docs, `SECURITY.md`, `TESTING_GUIDE.md`, `schema/doctor-v1.json` |

Interface 1 (`ak doctor --json`, `ak env`, `ak run`) is consumed by other tools: a change to it is a breaking change (see `docs/doctor.md`, `docs/run.md`).

## Validation

| Scope | Command |
| --- | --- |
| Full | `bash tests/run.sh` |
| Scoped | `bash tests/run.sh <scope>` |
| Public hygiene | `bash scripts/check-public-hygiene.sh` |

The test map lives in [`docs/TESTING_GUIDE.md`](docs/TESTING_GUIDE.md).

## Rules

1. English for code, comments and docs; conventional commits.
2. Runtime code depends on bash and the python3 standard library only.
3. Never print, log or write the value of any `*_API_KEY` / `*_TOKEN` variable; refer to variables by name.
4. Never spell a fetch-piped-to-shell install line in a skill file (marketplace rule E005); never inject a permission-bypass flag by default (E006); pin every cross-repo install to a tag (W012).
5. Developing is not installing: tests run in a sandbox `HOME`; nothing is installed into the real `$HOME` while developing.
6. Pin every external tool by version (GitHub Actions by commit SHA).
7. This repository is public: no personal paths, private organisation or repository names, internal tooling names or non-public addresses, ever — `scripts/check-public-hygiene.sh` enforces it in CI. Never rewrite published history.
8. Human contributors: [CONTRIBUTING.md](CONTRIBUTING.md). `CLAUDE.md` is a symlink to this file.

## Deep Work Plans

Structured work runs through the installed `deepworkplan` skill (`.agents/skills/deepworkplan/`); plans live in the gitignored `.dwp/`; only the addon registry `.dwp/config.json` is tracked (see the skill's `spec/CONFIG.md`).

DWP standard: 7.0.0 (onboarded 2026-10-08; upgraded 2026-10-09; skill 7.0.0)
