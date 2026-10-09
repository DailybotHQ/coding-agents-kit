# AGENTS.md — coding-agents-kit

Entry point for AI agents working **on** this repository.

## Purpose

Install and launch every terminal coding agent with one command surface: `ak <kind> [@profile]`. Canonical kinds (claude, codex, cursor, opencode, pi, cline, grok) plus provider variants (glm, azure, xai), multiple accounts per CLI through profiles, the same session flags everywhere, headless runs (`ak run`) and a doctor. Pass-through by default; autonomy is an explicit opt-in. API keys never land in config files.

## Command / skill

agentkit (alias ak); skill agentkit

## Layout (target; built by the first plan)

bin/ (ak, agentkit), lib/ (bash + python3 stdlib), providers.toml, skills/agentkit/, install.sh, install.ps1, win/, tests/ (run.sh), docs/

## Validation

| Scope | Command |
| --- | --- |
| Full | `bash tests/run.sh` |
| Scoped | `bash tests/run.sh <scope>` |

The test map lives in [`docs/TESTING_GUIDE.md`](docs/TESTING_GUIDE.md).

## Rules

1. English for code, comments and docs; conventional commits.
2. Runtime code depends on bash and the python3 standard library only.
3. Never print, log or write the value of any `*_API_KEY` / `*_TOKEN` variable; refer to variables by name.
4. Never spell a fetch-piped-to-shell install line in a skill file (marketplace rule E005); never inject a permission-bypass flag by default (E006); pin every cross-repo install to a tag (W012).
5. Developing is not installing: tests run in a sandbox `HOME`; nothing is installed into the real `$HOME` while developing.
6. Pin every external tool by version.

## Deep Work Plans

Structured work runs through the installed `deepworkplan` skill (`.agents/skills/deepworkplan/`); plans live in the gitignored `.dwp/`.

DWP standard: 6.0.0 (onboarded 2026-10-08; skill 6.1.0)
