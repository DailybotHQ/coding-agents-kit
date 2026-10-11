# Flow A — host install (macOS, Linux, WSL, Git Bash)

Requirements: bash, python3 3.9 or newer, git. Nothing else; no package is downloaded by the installer.

## Steps

1. Probe from a clone of the pinned tag (SKILL.md, step 0). `problems[]` lists blockers: an old python, no git, a home that is not writable, a loose env file.
2. If `git` or `python3` is missing, tell the user which and offer the platform's package manager command — `[GATE: system package]` (for example `apt-get install git`, `brew install git`). Run it only after they agree; never `sudo` on your own.
3. `[GATE: shell rc]` Ask whether the installer may add its guarded block to their shell rc. Without it, scripts and containers use `--no-rc`:
   ```bash
   # test: install
   bash coding-agents-kit/install.sh --no-rc
   ```
4. The installer prints the install path and how to run `ak`. With `--no-rc`, call `~/.local/share/agentkit/bin/ak` by path or let the user add that directory to PATH.
5. Verify (flow E).

## What the installer does — and nothing more

- Program in `~/.local/share/agentkit` (`AGENTKIT_HOME` moves it), mode 700. Env file `~/.config/agentkit/env` (mode 600), created only if missing, never overwritten.
- Never touches profiles, never installs a coding-agent CLI, never uses the network.
- Refuses a non-empty target that is not a kit install (exit 1) and deletes nothing.
- Idempotent: rerun it to upgrade in place.

## Edge cases

- **WSL** is Linux: use this flow inside the distribution, not in Windows.
- **macOS:** the default Claude Code login lives in the Keychain; `ak usage` reads only the default home's entry.
- **No TTY, closed stdin:** the installer never prompts.
- **Scripts and CI:** use `--no-rc`; set `AGENTKIT_HOME` and `AGENTKIT_ENV` to dedicated paths.
