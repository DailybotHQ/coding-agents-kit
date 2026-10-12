# Accounts: one CLI × one profile

Read this when the user wants a second account of a CLI, asks which accounts
exist, hits a login or key error on a profile, or wants a profile removed.
For quota and choosing an account, read [usage.md](usage.md).

## The model

An **account** is one CLI (or provider) × one profile.

- `@default` (also `@1`, or no `@` at all) is the CLI's own home
  (`~/.claude`, `~/.codex`, …). Nothing moves; nobody logs in again.
- `@name` is a directory under the kit's profiles root
  (`~/.local/share/agentkit/profiles/<cli>/<name>/`, mode 700) that `ak`
  points the CLI at. Kinds of the same CLI share it: `ak claude @work` and
  `ak claude-glm @work` see the same sessions and settings.
- A new profile starts empty: no settings, skills, MCP servers or plugins
  from `@default`.

| CLI | A profile isolates | Login lives | Key a profile reads | `ak usage` sees |
| --- | --- | --- | --- | --- |
| claude | `CLAUDE_CONFIG_DIR` | `.credentials.json`, or on macOS the Keychain item `Claude Code-credentials-<8 hex>` | `ZAI_CODING_API_KEY_<SUFFIX>` for `claude-glm` | 5-hour, 7-day all models, 7-day `<model>` only; plan |
| codex | `CODEX_HOME` | `auth.json` (ChatGPT login) | `ZAI_…`, `AZURE_OPENAI_API_KEY_…`, `XAI_API_KEY_…` for the variants | 5-hour, 7-day, resets available; plan |
| cursor | a `HOME` of its own | Keychain or web session; a profile uses a file store | — | connected only |
| opencode | the XDG directories | its auth store | provider keys | through the provider rows (Z.AI) |
| pi | `PI_CODING_AGENT_DIR` | — | provider keys | through the provider rows |
| cline | `CLINE_DIR` | — | provider keys | through the provider rows |
| grok | `GROK_HOME` | its own login | `XAI_API_KEY_<SUFFIX>`, optional | connected only |
| antigravity | a `HOME` of its own | its own login file (Linux, containers); one keyring slot per machine (macOS, Windows) | `GEMINI_API_KEY_<SUFFIX>`, optional | per-model quota buckets (file login); connected only (Keychain) |
| zai (provider) | — | — | `ZAI_CODING_API_KEY[_SUFFIX]` | 5-hour, 7-day credits |

## Lifecycle

1. **Add** (only when the user asked for the account):

   ```bash
   ak profiles add claude @work
   ```

2. **Log in as the profile**, so the login lands in the profile and not in
   the CLI's own home. Claude Code and Codex show their login the first time
   the profile opens; the user does that in a terminal:

   ```bash
   ak claude @work
   ak profiles run cursor @work -- agent login
   ak profiles run grok @work -- grok login
   ```

   A login is the user's action in their browser or terminal. Never type
   credentials for them and never ask them to paste one into the
   conversation.

3. **Check** that the account is there and readable:

   ```bash
   ak profiles                 # login yes/no/?, key names, path
   ak usage claude @work       # its windows, or the status that says what is missing
   ```

4. **Use** it: `ak claude @work`, or headless with
   `ak run claude @work --cwd <dir> -- "<prompt>"`.

5. **Remove** only when the user asks for that profile to be deleted. It
   deletes the profile's sessions and login:

   ```bash
   ak profiles rm claude @work --yes
   ```

## Keys per account, by name

A provider kind on a named profile reads `<KEY>_<SUFFIX>`: the profile name
in upper case with `-` and `.` turned into `_`.

| Profile | `*-glm` | `*-xai`, `grok` | `*-azure` | `antigravity` |
| --- | --- | --- | --- | --- |
| `@default` | `ZAI_CODING_API_KEY` | `XAI_API_KEY` | `AZURE_OPENAI_API_KEY` | `GEMINI_API_KEY` |
| `@work` | `ZAI_CODING_API_KEY_WORK` | `XAI_API_KEY_WORK` | `AZURE_OPENAI_API_KEY_WORK` | `GEMINI_API_KEY_WORK` |
| `@work-2` | `ZAI_CODING_API_KEY_WORK_2` | `XAI_API_KEY_WORK_2` | `AZURE_OPENAI_API_KEY_WORK_2` | `GEMINI_API_KEY_WORK_2` |

- A named profile **never falls back** to the default key. A missing key is
  exit 3 with the variable's name: tell the user which variable to set.
- The user puts keys in `~/.config/agentkit/env` (mode 600) themselves, or
  brings them over with `ak env import <file>`. Refer to variables by name
  only; never read, print or copy a value.
- `grok` and `antigravity` treat the key as optional: without it they use
  the profile's own login (grok; antigravity on Linux and in containers) or
  the machine's Google login (antigravity on macOS and Windows).

### A Claude token per account

`CLAUDE_CODE_OAUTH_TOKEN` (`@default`) or `CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`
(`@name`), made by the user with `claude setup-token`, logs a Claude profile
in without the browser login: useful in containers and on second machines.
A profile never inherits another's token. It gives no readable quota (`ak
usage` shows that account as needing a full login). Tell the user where it
goes; never ask for it or read it.

### The whole set, portable

`AGENTKIT_DEFAULT_PROFILE_<CLI>=@name` (environment or env file) makes that
account what a bare `ak <cli>` launches; `@profile`, `AGENTKIT_PROFILE` and an
explicit `@default` win. In a container, where a Mac's Keychain login cannot
follow, point it at a profile with a file or token-variable login; `pick`
(opt-in) launches the portable account with the most headroom.

`ak profiles --json` (schema `profiles-v1`) lists every account by name:
CLI, profile, relative path, isolation, login kind and the key names that
are set. Use it to recreate the accounts on another host; it never carries
a value.

## Platforms

- **macOS:** Claude Code keeps a profile's login in the Keychain item
  `Claude Code-credentials-<8 hex>` (derived from the profile directory).
  `ak profiles --json` reports `keychain` when that item exists (presence
  only, never the secret), `file` only with `.credentials.json`, and `none`
  when neither exists; `ak usage` asks the Keychain for that item only. After removing a profile
  the Keychain item stays until the user deletes it in Keychain Access.
- **Cursor** keeps its login under one fixed Keychain name, so its profiles
  get their own `HOME` and a file credential store.
- **Antigravity** keeps its Google login in a file of its home on Linux and
  in containers, so each profile is its own account: sign in inside it. On
  macOS and Windows it has one keyring slot per machine: signing in inside a
  profile replaces the login of every other Antigravity home, and a second
  account there is a `GEMINI_API_KEY_<SUFFIX>` key.
- **Windows:** profiles and logins are files under the same layout. A login
  kept in Windows Credential Manager is not readable by the kit and shows as
  `no_login` with that cause. A program calling the kit runs the core
  directly (`py -3 <install>\lib\ak.py …`), never `ak.cmd`.

## Common mistakes

| Mistake | What happens | Do instead |
| --- | --- | --- |
| Logging in with the plain CLI (`claude`, `agent login`) for a new account | the login lands in `@default` and replaces it | log in through `ak claude @name` or `ak profiles run <cli> @name -- <login>` |
| Expecting `@work` to use the default key | exit 3 naming `<KEY>_WORK` | ask the user to set that variable |
| Copying a login file between profiles | two profiles share one account and its quota | one login per profile |
| Creating or removing a profile to "free" quota | it changes the user's machine and frees nothing | create or remove only on request |
| Signing in to Antigravity inside a profile on macOS or Windows | every Antigravity home switches account (one keyring login per machine) | use `GEMINI_API_KEY_<SUFFIX>`; on Linux and in containers each profile keeps its own login |
| Syncing the profiles root to a shared drive | tokens leave the machine | keep it local (mode 700) |

Whether several subscriptions of one vendor may be used at once is that
vendor's terms: use only the accounts the user holds, as their terms allow.
