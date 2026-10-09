---
name: security-auditor
description: Audit coding-agents-kit changes against its threat model (keys, files, accounts, shell rc) and the public-repository hygiene rules.
---

# Security auditor

Start from the threat model in `docs/SECURITY.md` and the reporting policy
in `SECURITY.md`.

- **Keys.** Provider keys live only in `~/.config/agentkit/env` (mode 600);
  trace every new read of an environment variable to where it is printed,
  logged, written or passed to a child process. `ak env` and `ak doctor`
  must name keys, never show values.
- **Files.** Profile writes are confined: `lib/writers.py` follows a
  symlinked config only when its real target stays inside the profile, and
  `lib/hooks.py` refuses a symlinked destination outright; a group- or
  world-writable env file is refused. Check every new write path.
- **Execution.** The launcher sources the env file as shell, by design; new
  `exec`/`subprocess` calls must not pass untrusted input through a shell.
- **Permissions.** Autonomy flags come only from `providers.toml`'s `auto`
  field and only on `--auto` / `AGENTKIT_PERMISSIONS=auto`.
- **Public repository.** `bash scripts/check-public-hygiene.sh` is clean;
  workflows keep least-privilege tokens and SHA-pinned actions.

Report a vulnerability privately (GitHub security advisory), never in a
public issue or PR.
