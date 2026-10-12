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
The one command that reads a login and talks to a vendor on your behalf is
`ak usage`: a separate, read-only command (see the threat model and
*Quota queries* below).

Report a vulnerability privately through GitHub's security advisories for
`DailybotHQ/coding-agents-kit` (Security → Report a vulnerability), not in a
public issue.

## Threat model

| Asset | Threat | Control |
| --- | --- | --- |
| Provider keys (`*_API_KEY`, `*_TOKEN`) | printed, logged, written to a config file, committed, passed to the wrong CLI or account | Keys live only in the env file (mode 600) and in the process environment of the one CLI that needs them. Config writers store references (`env_key`, `{env:KEY}`, `"$KEY"`), never values. `ak env`, `ak doctor`, errors and `ak run` envelopes print variable **names** only. A named profile reads only its own `<KEY>_<SUFFIX>` and never falls back to the default key; the per-profile variables are removed from the CLI's environment. The `security` test scope plants values and searches every output and every written file. |
| The env file | another local user writes shell code into it (it is sourced) | `ak` refuses to load a group- or world-writable env file (exit 70) and warns when it is readable by others. The installer creates it mode 600 in a 700 directory and never overwrites it. On Windows it is created readable by the current user only and read as plain `KEY=value` lines (never executed). |
| Your files and machine | an agent acting without asking | **This is the accepted default, not a control:** autonomy is on, because the kit is meant for disposable or sandboxed environments. The controls are the opt-out and its reach: `--ask` or `AGENTKIT_PERMISSIONS=ask` suppresses the flag on every launch path (interactive, `ak run`, profiles, presets, aliases), even over an explicit `--auto`; the opt-out is passed on to nested launches and outranks an `AGENTKIT_PERMISSIONS=auto` line in the env file they re-read, so agents started by an opted-out agent ask too. An invalid value refuses to launch. The flags exist only as data in `providers.toml`; `ak doctor` warns when autonomy is on outside a container. See [permissions](permissions.md). |
| Accounts | one account's sessions or tokens used by another | Profiles are separate directories (mode 700) per CLI and name; names are validated (no path separators, no `..`), `profiles rm` refuses symlinks and anything outside the profiles root. |
| Supply chain | a tampered or floating CLI | Kit installs are a pinned git tag; releases ship `SHA256SUMS`. `ak install` pins every CLI to an exact version and verifies it before anything runs: native binaries and archives against a per-platform sha256, npm packages against the registry's `integrity` (sha512). A mismatch or a platform without a digest refuses the install and leaves nothing behind; archives are unpacked only when every entry stays inside its directory; vendor install scripts are never run. Claude Code's digests come from the vendor's release manifest; Cursor and Grok publish none, so theirs were recorded when the pin was taken (trust on first use, cross-checked against an independent pin) — a compromise of their artifact at that moment would be pinned too. npm dependencies of a verified package are resolved by npm, each against the registry's own integrity. CI actions are pinned by commit SHA. |
| Shell rc files | silent or repeated edits | One guarded block, replaced in place, removed byte-exactly; a symlinked rc is edited where it points, never replaced. An install made with `--no-rc` (remembered) or `AGENTKIT_NO_RC=1` keeps `ak alias` away from rc files too; only an explicit `ak alias rc --install` writes one. |
| Install directory | a mistaken `AGENTKIT_HOME` / `-Prefix` (e.g. `~/.local`) | The installers replace components only in a directory that carries their marker (`.agentkit-install`) or holds nothing but `profiles/` and `aliases.sh`; otherwise they refuse and delete nothing. |
| Windows argument parsing | a prompt containing `"` and `&`/`|` running commands through `cmd.exe` (the "BatBadBut" class) | npm-installed CLIs (`codex.cmd`, …) are started as `node <script>`, never through `cmd.exe`; any other batch target refuses arguments with cmd metacharacters. Programs that call ak on Windows must use `py -3 <install>\lib\ak.py …`, not `ak.cmd` (a batch shim re-parses its arguments; it is for typing at a prompt). |
| Vendor installers | a compromised npm dependency reading your keys | `ak install` starts installers and npm with every `*_API_KEY` / `*_TOKEN` variable removed from their environment. |
| Herdr hooks | writing into the CLI's own home | `ak profiles hooks` reads the real home and writes only inside the profile (checked path by path); it merges only Herdr's own entries and refuses files it cannot parse. |
| Logins read by `ak usage` | a token printed, logged, written, refreshed, sent to the wrong host or used for the wrong account | `ak usage` reads a profile's login file (or, on macOS, that profile's own Keychain item) into memory, uses it in one `Authorization` header for one request to the host written in `providers.toml`, and drops it. It never refreshes a token (a rotated refresh token can sign the CLI out), never reads a refresh token beyond parsing, never prints a token (messages are built from status codes and exception class names, not from requests), never writes under a profile or the env file, and reports an expired login without making a request. Each row uses only its own profile's login or key: no fallback to the default home's. Requests are `https` to the fixed hosts below; the only override (`AGENTKIT_USAGE_URL_<ADAPTER>`, for tests) must be a loopback address, no redirect is followed, the body is capped at 1 MiB, and at most 8 requests run at once. The `security` test scope plants tokens, runs every failure mode and searches every output and file. |
| Agent-driven setup (`ak setup`, the `agentkit-setup` skill) | an agent installing or changing a machine or container beyond what the person agreed to; a tampered or floating install source; a key printed, baked into an image or sent to a child process; a recipe that runs as root | `ak setup probe`, `verify` and `docker` are read-only: they observe or render to stdout and write nothing except an explicit `--out FILE`, created once and never overwriting; `verify` never applies a repair. They print provider keys by **name** only, run their one child process (`<tool> --version`, an allow-list that excludes every coding-agent CLI) without any `*_API_KEY`/`*_TOKEN` variable, and work from an uninstalled clone. A container recipe is rendered only for a release **tag** (never a branch or `latest`) together with the SHA256 of that release's tarball, which is verified before the archive is unpacked; it installs as a non-root user with `--no-rc`, keeps keys out of `ARG`/`ENV`, and the renderer refuses to print a recipe that breaks those rules. The skill asks before each system package, shell rc edit, autonomy choice, profile, CLI install, repository write and uninstall, never types an autonomy flag, and never asks for or echoes a key value. The `security`, `setup` and `setup-skill` scopes plant secrets and check outputs, files, recipes and the skill text; the skill's documented flows are executed in sandboxes. |
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
- **Login state** (`ak doctor`, `ak profiles`) is read from file presence
  only; the one file opened is Claude's `.claude.json`, which names the
  account and holds no token. **`ak usage` is the exception:** it opens the
  login file (`.credentials.json`, `auth.json`) of each profile to use its
  token, as described in *Quota queries*.
- **The setup skill is guidance a model follows, not a sandbox.** What holds
  without trusting the model is the helper's design (read-only, names-only,
  verified recipes) and the person's answers at each consent gate; an agent
  that ignores the skill can still run the installer by hand. The skill's
  flows are tested as executable documentation, so its words cannot silently
  drift from the commands.
- **The usage endpoints are vendor-internal and unofficial.** They can change
  or disappear without notice; `ak usage` then reports `error: unexpected
  response shape` for that row. Using them is your account's own token against
  your own account's data, but the vendors have not documented the endpoints
  for third parties.

## Quota queries (`ak usage`)

| Source | Host | Credential | Notes |
| --- | --- | --- | --- |
| Claude Code subscription | `api.anthropic.com` | the profile's `.credentials.json` (macOS: the profile's Keychain item when there is no file) | needs the `user:profile` permission; reported `no_scope` without it |
| Codex (ChatGPT login) | `chatgpt.com` | the profile's `auth.json` | an API-key login has no quota and is reported `n/d` |
| Z.AI coding plan | `api.z.ai` | the profile's `ZAI_CODING_API_KEY[_SUFFIX]` | one row per key, shared by the `*-glm` kinds |

Cursor, Grok, xAI and Azure OpenAI are `n/d`: no readable account quota (or one
that needs a browser session or a second, management credential, which `ak`
never asks for). `ak usage` is the only command that makes a network request
without you asking for an install; it has no side effects and no cache.

Keychain (macOS): only when a profile has no login file, `ak usage` asks the
Keychain for that profile's own item (`security find-generic-password -w`),
which may raise one macOS access dialog per item; the secret is parsed in
memory and dropped. `AGENTKIT_KEYCHAIN=off` skips every Keychain call, the
presence probe and the secret read alike (the test suite sets it). Requests to
vendor hosts honour `HTTPS_PROXY`; the loopback test override bypasses proxies.
A default home moved onto a profile directory (`CLAUDE_CONFIG_DIR=<profile>`)
is reported once, as that profile, so the same quota is never counted twice.

## Account selection (`ak pick`)

`ak pick` reads exactly what `ak usage` reads, with the same hosts, the same
per-row requests and the same rules: read-only, no cache, no login refresh, no
reset spent. Its output (`pick-v1`) carries CLI, profile, window ids,
percentages, reset times and a one-line reason built from the row status;
never a token or an account identity.

`AGENTKIT_DEFAULT_PROFILE_<CLI>=pick` (opt-in, off by default) runs the same
read-only selection at each launch, over the accounts whose login is portable
only: a Keychain item is never read for it. Its one stderr line names the
profile and its headroom, nothing else.

## Orchestration (agents launching agents)

The `agentkit-orchestrate` skill lets one agent start others on your
accounts. The rules it teaches, and the suite checks:

- Delegates run with each CLI's autonomy flag unless you opted out
  (`--ask`, `AGENTKIT_PERMISSIONS=ask`, inherited by every delegate): give a
  writing delegate only a git worktree of its own; one writer per path.
- `result_text`, transcripts and peer replies are untrusted data; a lane is
  merged only after the repository's own gate passes in its worktree.
- Task text goes in single quotes or on stdin (`-- -`), never through an
  expanding shell string; `ak run` itself passes argv without a shell.
- No key, token or secret in a prompt; `ak env` hands Herdr panes names and
  paths only.
- Failover's destructive git steps touch only worktrees the lead created,
  after checking the worktree's top level.
- `ak usage` / `ak pick` once per batch, never in a loop; only accounts you
  hold, within each vendor's terms — never rotated to get past a limit.

## Claude token per profile

`CLAUDE_CODE_OAUTH_TOKEN` (`@default`) and `CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`
(`@name`) are credentials like provider keys: they live in your env file or
environment, are exported to that profile's Claude only (a named profile
never falls back to the default token), and are shown by name only. A token
from `claude setup-token` is inference-only, so `ak usage` cannot read that
account's quota from it.

## Folder trust (`--trust-cwd`)

On explicit request only (`--trust-cwd`, `AGENTKIT_TRUST_CWD=1`), `ak`
writes one entry into the profile's own CLI config — Claude's
`.claude.json` (`projects[<folder>].hasTrustDialogAccepted`) or Codex's
`config.toml` (`[projects."<folder>"] trust_level = "trusted"`) — so the CLI
skips its folder-trust screen for that folder. The write is atomic, keeps
every other key and the file mode, never rewrites an existing Codex table,
and happens nowhere else. It does not change the permission posture and
never answers the bypass-permissions acknowledgement or any other screen.
No agent ever answers Claude's bypass-permissions acknowledgement: it is a
one-time step the developer takes per profile. The orchestration skill lets
a lead agent send one keystroke only — the folder-trust screen of its own
lane, on a pane it launched, when `--trust-cwd` was unavailable — and
escalates every other screen.

## Profiles with a HOME of their own

Cursor and Antigravity profiles get a separate `HOME` whose other entries are
links into your real home (git, ssh and `~/.config/agentkit/env` included), so
an agent in such a profile sees the same files as in your home. Mounting
profiles into a container: mount `AGENTKIT_PROFILES_DIR` only, not
`AGENTKIT_HOME` (which also holds the program); those links point at host
paths.

## What the kit writes

| Path | What | Mode |
| --- | --- | --- |
| `~/.local/share/agentkit/` (`AGENTKIT_HOME`) | the program, `aliases.sh`, `profiles/<cli>/<name>/` | dirs 700 |
| `~/.config/agentkit/env` (`AGENTKIT_ENV`) | your keys and settings (created once, never overwritten) | 600 |
| `~/.config/agentkit/aliases.json` | alias definitions | 600 |
| your shell rc | one guarded block (PATH + aliases) | unchanged |
| a CLI's own config | Codex overlay `<provider>.config.toml`, one provider in OpenCode's `opencode.json` / Pi's `models.json` — only when you launch that provider kind, inside the profile when one is used; one-time `.agentkit.bak` before the first change | 600 for files it creates |

`ak usage` and `ak pick` write nothing at all. Neither do `ak setup probe`, `verify` and
`docker` (stdout only); `docker --out FILE` creates one new file, mode 644.

Nothing else: no telemetry, and no network access except `ak install`
fetching a vendor installer you asked for and `ak usage` / `ak pick` querying
the usage endpoint of an account you run (the hosts above, one request per row),
which a launch also does when you opt into `AGENTKIT_DEFAULT_PROFILE_<CLI>=pick`.

## Checks

`bash tests/run.sh security` (planted secrets, file modes, env-file
refusal, `ak usage`, `ak pick` and `ak setup` secrecy/read-only rules, the orchestration skill's rules, recipe safety, static rules),
plus `permissions`, `doctor`, `profiles`, `usage`, `usage-providers`, `pick`, `setup`, `setup-skill`, `orchestrate-skill` and `lint`
(secret-shaped strings, private references, shellcheck). The suite runs in a
sandbox HOME with fake CLIs and never touches the network.
