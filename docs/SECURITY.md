# Security

coding-agents-kit starts programs that can read and change your files and
run commands. **Autonomy is the default:** every launch adds the CLI's own
autonomy flag, so an agent runs any command your user can run without asking
first. Autonomy is meant for disposable or sandboxed environments
(containers, virtual machines, throwaway worktrees). On a host you care
about, opt out with `--ask` on a launch or `AGENTKIT_PERMISSIONS=ask` in
`~/.config/agentkit/env`; the opt-out always wins. Beyond that choice, the
kit adds **no risk of its own**: no secret value leaves the place you put
it, and nothing is installed or written outside the paths documented here.

Report a vulnerability privately through GitHub's security advisories for
`DailybotHQ/coding-agents-kit` (Security → Report a vulnerability), not in a
public issue.

## Threat model

| Asset | Threat | Control |
| --- | --- | --- |
| Provider keys (`*_API_KEY`, `*_TOKEN`) | printed, logged, written to a config file, committed, passed to the wrong CLI or account | Keys live only in the env file (mode 600) and in the process environment of the one CLI that needs them. Config writers store references (`env_key`, `{env:KEY}`, `"$KEY"`), never values. `ak env`, `ak doctor`, errors and `ak run` envelopes print variable **names** only. A named profile reads only its own `<KEY>_<SUFFIX>` and never falls back to the default key; the per-profile variables are removed from the CLI's environment. The `security` test scope plants values and searches every output and every written file. |
| The env file | another local user writes shell code into it (it is sourced) | `ak` refuses to load a group- or world-writable env file (exit 70) and warns when it is readable by others. The installer creates it mode 600 in a 700 directory and never overwrites it. On Windows it is created readable by the current user only and read as plain `KEY=value` lines (never executed). |
| Your files and machine | an agent acting without asking | **This is the accepted default, not a control:** autonomy is on, because the kit is meant for disposable or sandboxed environments. The controls are the opt-out and its reach: `--ask` or `AGENTKIT_PERMISSIONS=ask` suppresses the flag on every launch path (interactive, `ak run`, profiles, presets, aliases), and the opt-out is passed on to nested launches, so agents started by an opted-out agent ask too. An invalid value refuses to launch. The flags exist only as data in `providers.toml`; `ak doctor` warns when autonomy is on outside a container. See [permissions](permissions.md). |
| Accounts | one account's sessions or tokens used by another | Profiles are separate directories (mode 700) per CLI and name; names are validated (no path separators, no `..`), `profiles rm` refuses symlinks and anything outside the profiles root. |
| Supply chain | a tampered or floating CLI | Kit installs are a pinned git tag; releases ship `SHA256SUMS`. `ak install` pins every CLI to an exact version and verifies it before anything runs: native binaries and archives against a per-platform sha256, npm packages against the registry's `integrity` (sha512). A mismatch or a platform without a digest refuses the install and leaves nothing behind; archives are unpacked only when every entry stays inside its directory; vendor install scripts are never run. Claude Code's digests come from the vendor's release manifest; Cursor and Grok publish none, so theirs were recorded when the pin was taken (trust on first use, cross-checked against an independent pin) — a compromise of their artifact at that moment would be pinned too. npm dependencies of a verified package are resolved by npm, each against the registry's own integrity. CI actions are pinned by commit SHA. |
| Shell rc files | silent or repeated edits | One guarded block, replaced in place, removed byte-exactly; a symlinked rc is edited where it points, never replaced. An install made with `--no-rc` (remembered) or `AGENTKIT_NO_RC=1` keeps `ak alias` away from rc files too; only an explicit `ak alias rc --install` writes one. |
| Install directory | a mistaken `AGENTKIT_HOME` / `-Prefix` (e.g. `~/.local`) | The installers replace components only in a directory that carries their marker (`.agentkit-install`) or holds nothing but `profiles/` and `aliases.sh`; otherwise they refuse and delete nothing. |
| Windows argument parsing | a prompt containing `"` and `&`/`|` running commands through `cmd.exe` (the "BatBadBut" class) | npm-installed CLIs (`codex.cmd`, …) are started as `node <script>`, never through `cmd.exe`; any other batch target refuses arguments with cmd metacharacters. Programs that call ak on Windows must use `py -3 <install>\lib\ak.py …`, not `ak.cmd` (a batch shim re-parses its arguments; it is for typing at a prompt). |
| Vendor installers | a compromised npm dependency reading your keys | `ak install` starts installers and npm with every `*_API_KEY` / `*_TOKEN` variable removed from their environment. |
| Herdr hooks | writing into the CLI's own home | `ak profiles hooks` reads the real home and writes only inside the profile (checked path by path); it merges only Herdr's own entries and refuses files it cannot parse. |
| Agent output | instructions smuggled through another agent's answer | `ak run` returns the agent's text as data (`result_text`); the bundled skill tells agents to treat it as a claim to verify, never as instructions. |

## Documented exceptions and limits

- **Cline takes its key on the command line.** `cline-azure` / `cline-xai`
  run `cline auth -k <key> …` and `cline -k <key> …` because Cline accepts
  no other way; Cline then stores the key in its own settings inside the
  profile. The key is visible to other local users in the process list for
  as long as that Cline process runs (the whole interactive session, since
  `ak` replaces itself with Cline). Every other kind receives keys through its environment
  only. The data model refuses `{key}` on any other CLI's command line.
- **Base provider keys are visible to every CLI you launch.** The env file
  is loaded into the launcher's environment, so `XAI_API_KEY` set there also
  reaches, say, `ak claude` — deliberately, because your own CLI configs may
  rely on it. Keep keys you do not want shared out of the env file.
- **Prompts are command-line arguments.** `ak run` passes the prompt to the
  CLI as an argument (each CLI's headless contract), so it is visible in the
  process list on a shared machine. Never put secrets in prompts. A prompt
  may not start with `-` (a CLI would read it as an option, possibly its
  autonomy flag).
- **The env file is code** on macOS/Linux (it is sourced by bash, which is
  what lets you fetch keys from a password manager). Only you should be able
  to write it; `ak` enforces that.
- **Login state** is read from file presence only; the one file opened is
  Claude's `.claude.json`, which names the account and holds no token.

## What the kit writes

| Path | What | Mode |
| --- | --- | --- |
| `~/.local/share/agentkit/` (`AGENTKIT_HOME`) | the program, `aliases.sh`, `profiles/<cli>/<name>/` | dirs 700 |
| `~/.config/agentkit/env` (`AGENTKIT_ENV`) | your keys and settings (created once, never overwritten) | 600 |
| `~/.config/agentkit/aliases.json` | alias definitions | 600 |
| your shell rc | one guarded block (PATH + aliases) | unchanged |
| a CLI's own config | Codex overlay `<provider>.config.toml`, one provider in OpenCode's `opencode.json` / Pi's `models.json` — only when you launch that provider kind, inside the profile when one is used; one-time `.agentkit.bak` before the first change | 600 for files it creates |

Nothing else: no telemetry, no network access except `ak install` fetching
a vendor installer you asked for.

## Checks

`bash tests/run.sh security` (planted secrets, file modes, env-file
refusal, static rules), plus `permissions`, `doctor`, `profiles` and `lint`
(secret-shaped strings, private references, shellcheck). The suite runs in a
sandbox HOME with fake CLIs and never touches the network.
