# Profiles — several accounts of the same CLI at once

Every kind takes an optional **profile** as its first argument. A profile is
a separate account: its own login, sessions, history and settings. Run
`ak claude` with your work account in one terminal and `ak claude @2` with a
second account in another, at the same time.

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
- Names are case-insensitive (`@Work` is `@work`) and use 1–32 letters,
  digits, `.`, `_` or `-`, not starting with `.`. `@02` is `@2`. Anything
  else is a one-line error (exit 2), never a path.
- **`--` sends everything after it to the CLI untouched.** Claude reads
  `@path` as a file mention, so `ak claude -- @src/app.ts explain this`
  passes the mention through instead of treating it as a profile.
- `AGENTKIT_PROFILE=@work` selects a profile for scripts and Herdr panes. A
  positional `@name` wins over it.

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

Provider kinds that use an API key need no login (see below).

## Where profiles live

```
~/.local/share/agentkit/profiles/<cli>/<name>/     (mode 700)
```

`<cli>` is `claude`, `codex`, `cursor`, `opencode`, `pi`, `cline` or `grok`.
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

A new profile starts empty: no settings, user skills, MCP servers or plugins
from profile 1. Copy what you want into it.

**Cursor** keeps its macOS login under one fixed Keychain name, so a second
account needs a separate `HOME` and the file credential store. `ak` links
every other entry of your real home (`.gitconfig`, `.ssh`, `.config`, …) into
`<profile>/home`, so git, gh and ssh keep working in the agent's shells.
**OpenCode** profiles get the same treatment for the XDG directories (all of
`~/.config` except `opencode/`, and so on).

## Provider keys per profile

Provider kinds (`claude-glm`, `codex-azure`, `opencode-xai`, `pi-glm`,
`cline-azure`, `grok`, …) read the profile's own key: `<KEY>_<SUFFIX>`, where
the suffix is the profile name in upper case with `-` and `.` turned into
`_`.

| Profile | `*-glm` | `*-xai`, `grok` | `*-azure` |
| --- | --- | --- | --- |
| none / `@default` | `ZAI_CODING_API_KEY` | `XAI_API_KEY` | `AZURE_OPENAI_API_KEY` |
| `@2` | `ZAI_CODING_API_KEY_2` | `XAI_API_KEY_2` | `AZURE_OPENAI_API_KEY_2` |
| `@work` | `ZAI_CODING_API_KEY_WORK` | `XAI_API_KEY_WORK` | `AZURE_OPENAI_API_KEY_WORK` |
| `@client-x` | `ZAI_CODING_API_KEY_CLIENT_X` | `XAI_API_KEY_CLIENT_X` | `AZURE_OPENAI_API_KEY_CLIENT_X` |

Put them in `~/.config/agentkit/env` (mode 600). A missing key is an error
(exit 3) that names the variable; **ak never falls back to profile 1's
key**. `grok` treats the key as optional: with no `XAI_API_KEY_<SUFFIX>` it
uses that profile's own `grok login`. The CLI receives the key under the
base name (`ZAI_CODING_API_KEY`, …); the per-profile variables themselves
are removed from the CLI's environment.

Non-secret settings follow the same rule when you set them
(`AZURE_OPENAI_RESOURCE_2`, `AZURE_OPENAI_BASE_URL_2`, `XAI_BASE_URL_2`,
`ZAI_CODING_BASE_URL_2`, `ZAI_CODEX_BASE_URL_2`, `ZAI_ANTHROPIC_BASE_URL_2`);
unset ones keep profile 1's value, and model names are shared.

The provider config the writers produce (Codex `<provider>.config.toml`,
OpenCode `opencode.json`, Pi `models.json`) goes inside the profile, so
`ak codex-glm @2` never touches `~/.codex`.

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
from file presence only (`?` when the CLI's login cannot be seen from files,
e.g. Cursor's default Keychain login); no credential is ever read.

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
  is the provider's terms, and yours to check.
- A profile directory holds that account's tokens (Codex, Cursor, OpenCode,
  Pi, Cline and Grok keep them in files). It is mode 700; do not sync it to a
  shared drive.
