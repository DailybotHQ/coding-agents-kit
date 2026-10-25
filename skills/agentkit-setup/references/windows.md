# Flow B — Windows (PowerShell 5.1 or 7)

Requirements: python 3.9 or newer (the `py` launcher), git. WSL users follow flow A inside the distribution instead.

## Steps

1. Probe: `py -3 coding-agents-kit\lib\ak.py setup probe --json` (after `git clone --branch v1.0.1 https://github.com/DailybotHQ/coding-agents-kit`).
2. Missing git or python: offer `winget install Git.Git` or `winget install Python.Python.3.12` — `[GATE: system package]`; run only after they agree.
3. `[GATE: shell rc]` The installer adds the install's `bin` to the **user** Path unless told not to:
   ```powershell
   .\coding-agents-kit\install.ps1 -NoPath
   ```
   Drop `-NoPath` only after the user agrees to a PATH change.
4. Verify: `& "$HOME\.local\share\agentkit\bin\ak.cmd" setup verify`.

## Windows specifics

- People type `ak.cmd`. A **program** that calls ak must start the core directly — `py -3 <install>\lib\ak.py <args>` — never `ak.cmd`: a batch file lets `cmd.exe` re-parse its arguments.
- The env file `%USERPROFILE%\.config\agentkit\env` is read as plain `KEY=value` lines (never executed) and is readable by the current user only.
- `-Prefix` and `-EnvFile` move the install and the env file; `-Uninstall` removes the program and keeps the env file and profiles.
- Git Bash is POSIX: use flow A there, with the Windows caveats above for anything a program starts.
