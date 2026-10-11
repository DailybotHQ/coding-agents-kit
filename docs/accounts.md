# Accounts — one CLI × one profile

The kit treats every login or key you hold as an **account**: one CLI (or
provider) × one profile. This page is the account model end to end. The
command reference for profiles is [Profiles](profiles.md); quota and choosing
an account are in [`ak usage`](usage.md); running work over several accounts
is in [Orchestration](orchestration.md).

## Concepts

- **`@default`** (also `@1`, or no `@` at all) is the CLI's own home:
  `~/.claude`, `~/.codex`, … Nothing moves and nobody logs in again.
- **`@name`** is a directory under the profiles root
  (`~/.local/share/agentkit/profiles/<cli>/<name>/`, mode 700) that `ak`
  points the CLI at. It has its own login, sessions, history and settings.
- Kinds of one CLI share its profiles: `ak claude @work` and
  `ak claude-glm @work` see the same sessions and settings.
- A profile starts empty: no settings, skills, MCP servers or plugins from
  `@default`.
- A provider key belongs to a profile by its name (`<KEY>_<SUFFIX>`), and a
  provider (Z.AI) is an account of its own in `ak usage`.

```text
CLI          profile            login or key                          ak usage row
claude  ──▶  @default     ──▶  ~/.claude login                   ──▶  claude @default  (5-hour, 7-day, 7-day <model>)
        ──▶  @work        ──▶  <profiles>/claude/work login      ──▶  claude @work
claude-glm   @work        ──▶  ZAI_CODING_API_KEY_WORK           ──▶  zai @work        (5-hour, 7-day credits)
codex   ──▶  @work        ──▶  <profiles>/codex/work/auth.json   ──▶  codex @work      (5-hour, 7-day, resets)
cursor  ──▶  @default     ──▶  Keychain / web session            ──▶  connected, no quota to read
```

## Per CLI

| CLI | A profile isolates | Login lives | Key a profile reads | `ak usage` sees |
| --- | --- | --- | --- | --- |
| claude | `CLAUDE_CONFIG_DIR` | `.credentials.json`, or on macOS the Keychain item `Claude Code-credentials-<8 hex>` | `ZAI_CODING_API_KEY_<SUFFIX>` for `claude-glm` | 5-hour, 7-day all models, 7-day `<model>` only; plan |
| codex | `CODEX_HOME` | `auth.json` (ChatGPT login) | `ZAI_…`, `AZURE_OPENAI_API_KEY_…`, `XAI_API_KEY_…` for the variants | 5-hour, 7-day, resets available; plan |
| cursor | a `HOME` of its own | Keychain or web session; a profile uses a file store | — | connected only |
| opencode | the XDG directories | its auth store | provider keys | through the provider rows (Z.AI) |
| pi | `PI_CODING_AGENT_DIR` | — | provider keys | through the provider rows |
| cline | `CLINE_DIR` | — | provider keys | through the provider rows |
| grok | `GROK_HOME` | its own login | `XAI_API_KEY_<SUFFIX>`, optional | connected only |
| antigravity | a `HOME` of its own | one keyring slot per machine | `GEMINI_API_KEY_<SUFFIX>` is the profile's own account | connected only |
| zai (provider) | — | — | `ZAI_CODING_API_KEY[_SUFFIX]` | 5-hour, 7-day credits |

How each CLI is pointed at a profile, file by file, is in
[Profiles → Where profiles live](profiles.md#where-profiles-live).

## Lifecycle

1. **Add** the profile:

   ```bash
   ak profiles add claude @work
   ```

2. **Log in as the profile**, so the login lands in the profile and not in
   the CLI's own home. Claude Code and Codex show their login the first
   time the profile opens; other CLIs have a login command you run as the
   profile:

   ```bash
   ak claude @work
   ak profiles run cursor @work -- agent login
   ak profiles run grok @work -- grok login
   ```

3. **Check** it:

   ```bash
   ak profiles                 # login yes/no/?, key names, path
   ak usage claude @work       # its windows, or the status that says what is missing
   ```

4. **Use** it: `ak claude @work` in a terminal,
   `ak run claude @work --cwd <dir> -- "<prompt>"` headless, or let
   `ak pick claude` choose the account with the most room.

5. **Remove** it only when you mean to: it deletes the profile's sessions
   and login.

   ```bash
   ak profiles rm claude @work
   ```

An agent using the kit follows the same lifecycle, and creates or removes
a profile only when you ask it to.

## Keys per account, by name

A provider kind on a named profile reads `<KEY>_<SUFFIX>`: the profile name
in upper case with `-` and `.` turned into `_`.

| Profile | `*-glm` | `*-xai`, `grok` | `*-azure` | `antigravity` |
| --- | --- | --- | --- | --- |
| `@default` | `ZAI_CODING_API_KEY` | `XAI_API_KEY` | `AZURE_OPENAI_API_KEY` | `GEMINI_API_KEY` |
| `@work` | `ZAI_CODING_API_KEY_WORK` | `XAI_API_KEY_WORK` | `AZURE_OPENAI_API_KEY_WORK` | `GEMINI_API_KEY_WORK` |
| `@work-2` | `ZAI_CODING_API_KEY_WORK_2` | `XAI_API_KEY_WORK_2` | `AZURE_OPENAI_API_KEY_WORK_2` | `GEMINI_API_KEY_WORK_2` |

- Keys live in `~/.config/agentkit/env` (mode 600); `ak env import <file>`
  copies `KEY=value` lines from another env file and prints names only.
- A named profile **never falls back** to the default key: a missing key is
  exit 3 naming the variable.
- `grok` and `antigravity` treat the key as optional: without it they use
  the profile's own login (grok) or the machine's Google login (antigravity).
- Non-secret settings follow the same suffix rule; see
  [Profiles → Provider keys per profile](profiles.md#provider-keys-per-profile).

## A Claude login token per account

Claude Code can log in with a long-lived token instead of the browser login
(`claude setup-token`, run once per account). Put it in the env file:
`CLAUDE_CODE_OAUTH_TOKEN` for `@default`, `CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`
for a named profile (`CLAUDE_CODE_OAUTH_TOKEN_WORK` for `@work`). `ak claude
@work` (and `ak run`, `ak env`) gives that profile its own token as
`CLAUDE_CODE_OAUTH_TOKEN`; a profile without one gets none, never
`@default`'s. `ak profiles` and `ak doctor` show the variable by name, and a
profile with its token set counts as logged in.

Use it where the browser login cannot follow the account: a container that
mounts the host's profiles (the macOS login lives in the Keychain, which a
Linux container cannot read), or a second machine. The token is
inference-only: `ak usage` / `ak pick` cannot read that account's quota from
it, so query quota on a host that has the browser login.

## Another host

To reuse the same set of accounts elsewhere, read `ak profiles --json`
(schema `profiles-v1`: names and kinds only) and recreate each with
`ak profiles add`; log each in there, or give Claude profiles a login token
(above). See [Profiles → A portable listing](profiles.md#a-portable-listing-ak-profiles---json).

## Platforms

- **macOS:** Claude Code keeps a profile's login in the Keychain item
  `Claude Code-credentials-<8 hex>` (the first 8 hex of the sha256 of the
  profile directory). `ak profiles` reads files only, so it shows `login ?`;
  `ak usage` asks the Keychain for that item. Removing a profile leaves the
  item until you delete it in Keychain Access.
- **Cursor** keeps its macOS login under one fixed Keychain name, so a
  profile gets its own `HOME` and a file credential store.
- **Antigravity** has one keyring slot per machine: signing in inside a
  profile replaces the login of every other Antigravity home. A second
  account is a `GEMINI_API_KEY_<SUFFIX>` key.
- **Windows:** profiles and logins are files in the same layout. A login in
  Windows Credential Manager (or a Codex keyring) is not readable by the kit
  and shows as `no_login` with that cause. A program calling the kit starts
  the core directly (`py -3 <install>\lib\ak.py …`), never `ak.cmd`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| The new account opened as the old one | you logged in with the plain CLI, so the login went to `@default` | log in through `ak claude @name` or `ak profiles run <cli> @name -- <login>` |
| exit 3 naming `<KEY>_WORK` | the profile's own key is not set (there is no fallback) | add that variable to `~/.config/agentkit/env` |
| `ak usage` says `expired` | the login passed its own expiry | open the profile once (`ak claude @work`); the CLI renews it |
| `ak usage` says `no_login` | no readable login for that profile | log in as the profile; on Windows, a credential-store login cannot be read |
| `ak usage` says `no_scope` | the login lacks the usage permission or was rejected | sign in again with a full login |
| `login ?` in `ak profiles` on macOS | the login is in the Keychain, which `ak profiles` does not read | `ak usage claude @work` tells whether it works |
| Two profiles show the same quota | a login file was copied between them | one login per profile; log in again in one of them |
| Every Antigravity home switched account | someone signed in inside a profile | use `GEMINI_API_KEY_<SUFFIX>` for the second account |

Whether several subscriptions of one vendor may be used at once is that
vendor's terms, and yours to check.
