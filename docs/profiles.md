# Profiles — several accounts of the same CLI at once

Every kind takes an optional **profile** as its first argument. A profile is
a separate account: its own login, sessions, history and settings. Run
`ak claude` with your work account in one terminal and `ak claude @2` with a
second account in another, at the same time.

This page is the command reference. The account model end to end (what a
profile isolates per CLI, the lifecycle, keys, macOS and Windows,
troubleshooting) is [Accounts](accounts.md); which account has room is
[`ak usage` and `ak pick`](usage.md#choosing-an-account).

```bash
ak claude              # the CLI's own home, exactly as `claude`
ak claude @2           # a second Claude account
ak claude @work -c     # continue the newest session of the "work" account
ak codex @client-x     # a Codex account named client-x
ak claude-glm @2       # Z.AI through Claude Code, with ZAI_CODING_API_KEY_2
```

## Syntax

```
ak <kind> [@profile] [--ask | --auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
```

- **Only the first argument after the kind (ignoring `--ask` and `--auto`) can be a
  profile, and only when it starts with `@`.** `@2`, `@work`, `@client-x`.
  Anything else behaves exactly as the CLI expects: `ak claude 2` sends the
  prompt "2", `ak claude mcp list` runs that subcommand.
- **`@default` and `@1` are the CLI's own home** (`~/.claude`, `~/.codex`, …).
  No `@` at all means the same thing. Nothing moves; nobody logs in again.
- **Every profile is its own account, `@default` included.** A home variable
  that names one of ak's profiles — `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
  `PI_CODING_AGENT_DIR`, `CLINE_DIR`, `GROK_HOME`, an `XDG_*` directory or a
  relocated `HOME` inherited from an `ak <cli> @work` session, or exported by a
  dev container so that a plain `claude --resume` opens its default account —
  is ignored for `@default`: launching, `ak usage`, `ak pick` and
  `ak profiles` read and run the CLI's own home. A home variable outside ak's
  profile tree (a home you moved on purpose) is still `@default`'s home.
- Names are case-insensitive (`@Work` is `@work`) and use 1–32 letters,
  digits, `.`, `_` or `-`, not starting with `.`. `@02` is `@2`. Anything
  else is a one-line error (exit 2), never a path.
- **`--` sends everything after it to the CLI untouched.** Claude reads
  `@path` as a file mention, so `ak claude -- @src/app.ts explain this`
  passes the mention through instead of treating it as a profile.
- `AGENTKIT_PROFILE=@work` selects a profile for scripts and Herdr panes. A
  positional `@name` wins over it.
- `AGENTKIT_DEFAULT_PROFILE_<CLI>=@work` makes `@work` the account a bare
  `ak <cli>` launches (see [A default profile per CLI](#a-default-profile-per-cli)).

## A default profile per CLI

`AGENTKIT_DEFAULT_PROFILE_<CLI>` (`AGENTKIT_DEFAULT_PROFILE_CLAUDE`,
`AGENTKIT_DEFAULT_PROFILE_CODEX`, …) names the account `ak <cli>`, `ak run
<cli>` and `ak env <cli>` use when no `@profile` is given. Set it in the
environment or as a line of the env file (`~/.config/agentkit/env`), which is
the kit's configuration:

```bash
AGENTKIT_DEFAULT_PROFILE_CLAUDE=@work3
```

- Precedence: a positional `@name`, then `AGENTKIT_PROFILE`, then
  `AGENTKIT_DEFAULT_PROFILE_<CLI>`, then the CLI's own home. **An explicit
  `@default` always means the CLI's own home.**
- Values: `@name` (or `name`), `@default`, or `pick` (below). `@pick` is a
  profile named pick. Anything else is a usage error (exit 2) naming the
  variable.
- The profile must exist: a default never creates one (exit 3, naming the
  variable and `ak profiles add`).
- It applies to the CLI's own kind only (`ak claude`, not `ak claude-glm`):
  a provider kind reads its key per profile, so it keeps the CLI's own home.
- `ak usage` and `ak pick` mark that account (`@work3 (ak claude)`;
  `"default": true` in `usage-v1` / `pick-v1`), `ak profiles --json` marks it
  (`"default": true`), and `ak doctor` lists it under Profiles
  (`default_profiles` in `doctor-v1`), with a problem when the profile does
  not exist.

**Why: a container.** A Mac keeps Claude's default login in the macOS
Keychain, which cannot be shared into Linux, so inside a container a bare
`ak claude` would start logged out. Point it at a profile whose login is a
file (`.credentials.json`) or a token variable (`CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`)
and `ak claude` works there as it does on the Mac. On Linux or in a container,
`ak doctor` names each account whose file names the account but whose token
is not there, with this fix.

**`pick`** (opt-in, off by default): `AGENTKIT_DEFAULT_PROFILE_CLAUDE=pick`
launches the account with the most headroom by [`ak pick`'s
policy](usage.md#choosing-an-account), among the accounts whose login is
portable (a file or a token variable; never a Keychain item). It asks every
such account's vendor at each launch and says on stderr which one it chose;
when none has room it launches `@default`.

## Codex and its app-server daemon

Codex installs an app-server daemon under its home
(`packages/app-server-daemon/current/bin/codex`) and records it there. A
home shared with another machine — a host profile mounted into a container,
or one Codex volume shared by several containers — records a daemon that is
not on this machine, or one built for another OS, and Codex refuses to
start (`daemon executable not found`). When the home records a daemon that
cannot run here, an interactive `ak codex` adds `--no-daemon` (before your
own arguments, and not twice); where the daemon is present it never adds it.
`AGENTKIT_CODEX_NO_DAEMON=1` adds it always. `ak doctor` reports the state
of each account (`daemons`). A presence check only: the daemon is never run.

A running daemon keeps the environment of whoever started it, and Codex runs
its tool shells from it — so a shell inside the session would not see the
launch's `AGENTKIT_ACTIVE_ACCOUNT` (`ak capacity --self`). Since 0.6.1, when
the daemon is present an interactive `ak codex` passes the marker for the
session first, as a config override:
`-c shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT="<kind>/@<profile>"`
(providers.toml `[clis.codex.daemon] marker`; not twice). With no daemon
recorded Codex starts one from the launch's own environment, and with
`--no-daemon` the shells are the launch's children: no override is needed.

## Creating a profile

The first time you use a profile in a terminal, `ak` asks:

```
ak: claude profile "@work" does not exist. Create it? [y/N]
```

Only `y` creates it (and then launches the CLI). Anything else exits without
creating or launching anything, so a typo never opens the wrong account.
With no terminal (a script, CI, a pane started without a TTY) it stops with
exit 3 and names the command to run instead:

```bash
ak profiles add claude @work
```

**Log in once inside the new profile.** Claude Code and Codex show their
login on the first launch. For a CLI whose login is a separate command, run
it as the profile so the token lands there:

```bash
ak profiles run cursor @2 -- agent login
ak profiles run grok @2 -- grok login
ak profiles run opencode @2 -- opencode auth login
ak profiles run cline @2 -- cline auth
```

**Antigravity** depends on the OS. On Linux and in containers `agy` reaches
no OS keyring and keeps its Google login in a file of its home
(`antigravity-cli/antigravity-oauth-token`), so every profile is its own
account: sign in inside it, and several run side by side. On macOS and
Windows the login sits in one OS-keyring slot per machine (Keychain item
`gemini`/`antigravity`, Credential Manager), so signing in inside a profile
replaces the login every other Antigravity home uses; for a second account
there give the profile its own key — `GEMINI_API_KEY_<SUFFIX>` in the env
file — and `ak antigravity @name` uses it (see below). `ak profiles add
antigravity @name` says so when it creates the profile.

Provider kinds that use an API key need no login (see below).

## Where profiles live

```
~/.local/share/agentkit/profiles/<cli>/<name>/     (mode 700)
```

`<cli>` is `claude`, `codex`, `cursor`, `opencode`, `pi`, `cline`, `grok` or `antigravity`.
`AGENTKIT_PROFILES_DIR` moves the root. Kinds of the same CLI share a
profile: `ak claude @2` and `ak claude-glm @2` see the same sessions and
settings.

| CLI | How ak points it at the profile | Login stored in |
| --- | --- | --- |
| Claude Code | `CLAUDE_CONFIG_DIR=<profile>` | macOS Keychain, one entry per profile directory (`Claude Code-credentials-<id>`); `<profile>/.claude.json` names the account |
| Codex | `CODEX_HOME=<profile>` | `<profile>/auth.json` |
| Cursor | its own `HOME=<profile>/home`, `AGENT_CLI_CREDENTIAL_STORE=file`, `CURSOR_CONFIG_DIR` | `<profile>/home/.cursor/auth.json` |
| OpenCode | `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` under the profile | `<profile>/data/opencode/auth.json` |
| Pi | `PI_CODING_AGENT_DIR=<profile>` | `<profile>/auth.json` |
| Cline | `CLINE_DIR=<profile>` | `<profile>/data/settings/` |
| Grok | `GROK_HOME=<profile>` | `<profile>/auth.json` |
| Antigravity | its own `HOME=<profile>/home` (state in `<profile>/home/.gemini`) | Linux, containers: `<profile>/home/.gemini/antigravity-cli/antigravity-oauth-token`; macOS, Windows: the OS keyring, one slot per machine — a profile's own account there is `GEMINI_API_KEY_<SUFFIX>` |

A new profile starts empty: no settings, user skills, MCP servers or plugins
from profile 1. Copy what you want into it.

**Cursor** keeps its macOS login under one fixed Keychain name, so a second
account needs a separate `HOME` and the file credential store. `ak` links
every other entry of your real home (`.gitconfig`, `.ssh`, `.config`, …) into
`<profile>/home`, so git, gh and ssh keep working in the agent's shells.
**Antigravity** profiles get the same separate `HOME` (its own `.gemini`:
conversations, settings, trusted folders, and on Linux and in containers the
login file too). On macOS and Windows agy keeps the login in the OS keyring
instead, which is why a profile's own account there is its key.
**OpenCode** profiles get the same treatment for the XDG directories (all of
`~/.config` except `opencode/`, and so on).

## Provider keys per profile

Provider kinds (`claude-glm`, `codex-azure`, `opencode-xai`, `pi-glm`,
`cline-azure`, `grok`, …) read the profile's own key: `<KEY>_<SUFFIX>`, where
the suffix is the profile name in upper case with `-` and `.` turned into
`_`.

| Profile | `*-glm` | `*-xai`, `grok` | `*-azure` | `antigravity` |
| --- | --- | --- | --- | --- |
| none / `@default` | `ZAI_CODING_API_KEY` | `XAI_API_KEY` | `AZURE_OPENAI_API_KEY` | `GEMINI_API_KEY` |
| `@2` | `ZAI_CODING_API_KEY_2` | `XAI_API_KEY_2` | `AZURE_OPENAI_API_KEY_2` | `GEMINI_API_KEY_2` |
| `@work` | `ZAI_CODING_API_KEY_WORK` | `XAI_API_KEY_WORK` | `AZURE_OPENAI_API_KEY_WORK` | `GEMINI_API_KEY_WORK` |
| `@client-x` | `ZAI_CODING_API_KEY_CLIENT_X` | `XAI_API_KEY_CLIENT_X` | `AZURE_OPENAI_API_KEY_CLIENT_X` | `GEMINI_API_KEY_CLIENT_X` |

Put them in `~/.config/agentkit/env` (mode 600). A missing key is an error
(exit 3) that names the variable; **ak never falls back to profile 1's
key**. `grok` and `antigravity` treat the key as optional: with no
`XAI_API_KEY_<SUFFIX>` grok uses that profile's own `grok login`, and with no
`GEMINI_API_KEY_<SUFFIX>` agy uses the profile's own Google login (Linux, containers) or the machine's (macOS, Windows). The CLI receives the key under the
base name (`ZAI_CODING_API_KEY`, …); the per-profile variables themselves
are removed from the CLI's environment.

Non-secret settings follow the same rule when you set them
(`AZURE_OPENAI_RESOURCE_2`, `AZURE_OPENAI_BASE_URL_2`, `XAI_BASE_URL_2`,
`ZAI_CODING_BASE_URL_2`, `ZAI_CODEX_BASE_URL_2`, `ZAI_ANTHROPIC_BASE_URL_2`);
unset ones keep profile 1's value, and model names are shared.

The provider config the writers produce (Codex `<provider>.config.toml`,
OpenCode `opencode.json`, Pi `models.json`) goes inside the profile, so
`ak codex-glm @2` never touches `~/.codex`.

## A Claude login token per account

`CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>` in the env file (from `claude setup-token`)
logs a named Claude profile in without the browser login; `@default` reads
`CLAUDE_CODE_OAUTH_TOKEN`. A profile never inherits another's token. See
[Accounts → A Claude login token per account](accounts.md#a-claude-login-token-per-account).

## A portable listing: `ak profiles --json`

`ak profiles --json` (also `ak profiles ls --json`) prints one object, schema
`profiles-v1` ([`schema/profiles-v1.json`](schema/profiles-v1.json)): every
account with its CLI, profile, path relative to the profiles root (`null` for
`@default`), isolation, how it is logged in (`file`, `keychain`, `token-var`,
`none` or `unknown`, by presence only) and the names of the keys it reads that
are set. No value, no identity, no absolute path: another host (a container,
a second machine) recreates the same set with `ak profiles add <cli> @<name>`
and logs each one in. Additive surface; interface 1 is unchanged.

```json
{"schema": "profiles-v1", "interface": 1, "profiles": [
 {"cli": "claude", "profile": "@work", "path_relative": "claude/work", "isolation": "env",
  "login": "token-var", "key_names_set": ["CLAUDE_CODE_OAUTH_TOKEN_WORK"]}]}
```

## Managing profiles

```bash
ak profiles                        # list: CLI, profile, login yes/no/?, keys by name, path
ak profiles add claude @2          # create without launching (scripts, no terminal)
ak profiles path codex @work       # print the directory (@default prints the CLI's own home)
ak profiles run cursor @2 -- agent status   # any command, as that profile
ak profiles rm claude @2           # delete it, with its sessions and login (asks first)
ak profiles rm claude @2 --yes
ak profiles hooks claude @2        # copy Herdr's state hooks into the profile
```

`<cli>` is the CLI or any of its kinds (`claude-glm`). `profiles rm` refuses
`@default`, refuses a profile that resolves outside the profiles root, and
needs `--yes` when there is no terminal. Claude's token for a removed
profile stays in the macOS Keychain until you delete the
`Claude Code-credentials-<id>` entry in Keychain Access. Login is reported
by presence only: login files, credential variable names and macOS Keychain
items (asked without the secret; never under `AGENTKIT_KEYCHAIN=off`); no
credential is ever read. For Claude, `.claude.json` only names the account:
the login is `file` with `.credentials.json`, `keychain` with the
`Claude Code-credentials` item (`-<id>` for a profile), `none` with neither,
and `unknown` (`?`) when only `.claude.json` is there and the Keychain cannot
be asked.

## Herdr

A Herdr pane runs whatever you type, so `ak claude @2` in a pane is all it
takes. To pin a pane to one account:

```bash
AGENTKIT_PROFILE=@work ak claude -c
```

To let Herdr launch the CLI itself in a profile, pass the profile's
environment: `ak env <kind> @name` prints it (see [doctor and env](doctor.md)).
Herdr's agent-state hooks are installed into the CLI's own home by
`herdr integration install <cli>`; copy them into a profile with
`ak profiles hooks <cli> @name` so Herdr sees that profile's state too.

### Herdr's state hooks in a profile

`herdr integration install <cli>` installs Herdr's agent-state hooks into the
CLI's own home only. Copy them into a profile once (after installing them in
Herdr, and again after Herdr updates its integration):

```bash
ak profiles hooks claude @work
```

| CLI | Files copied into the profile | Registration merged |
| --- | --- | --- |
| claude | `hooks/herdr-agent-state.sh` | `settings.json` (`hooks`) |
| codex | `herdr-agent-state.sh` | `hooks.json` |
| cursor | `home/.cursor/herdr-agent-state.sh` | `home/.cursor/hooks.json` |
| opencode | `config/opencode/plugins/herdr-agent-state.js` | — (plugins load by location) |
| pi | `extensions/herdr-agent-state.ts` | — |
| grok | `hooks/herdr-agent-state.sh`, `hooks/herdr.json` | — (copied, path rewritten) |

Only Herdr's own entries are merged (their paths rewritten to the profile);
the profile's other settings and hooks are kept, and a profile file that
does not parse is refused and left untouched. The real home is read, never
written. Rerunning is a no-op. Cline has no Herdr integration (Herdr reads
its screen). `ak doctor` shows `herdr_hooks` per profile.

## Limits

- Whether running several subscriptions of one provider at once is allowed
  is the provider's terms, and yours to check. Spreading work over your
  accounts: [Orchestration](orchestration.md).
- A profile directory holds that account's tokens (Codex, Cursor, OpenCode,
  Pi, Cline and Grok keep them in files). It is mode 700; do not sync it to a
  shared drive.
