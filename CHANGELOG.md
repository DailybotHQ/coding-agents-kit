# Changelog

All notable changes to coding-agents-kit are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Since 1.0.0 the public interface follows semver: a breaking change bumps the
major version (before 1.0.0, while the version was `0.x`, it bumped the minor
version). The interface version reported by `ak doctor --json` tracks the machine contract
only (the doctor JSON shape, `ak env`, the `ak run` grammar and envelope): it
changes when that contract breaks, not when behaviour such as the default
permission posture changes.

## [Unreleased]

### Changed

- **`ak usage` lists the measurable blocks first.** The table shows the CLIs
  and providers whose quota `ak` can read (at least one account read, or
  whose read failed) before the blocks where every account is `n/d` or
  `no login` — Z.AI now sits above Cursor and Grok. Each part keeps the kit
  order; `--json` is not reordered.

## [1.0.1] - 2026-10-13

A fix release. Interface stays **1**; no command, flag, key or schema changes.

### Fixed

- **Every profile is its own account, `@default` included.** A CLI home
  variable that names one of ak's profiles — inherited from an
  `ak <cli> @work` session, or exported by a dev container so that a plain
  `claude --resume` restored by Herdr opens its default account
  (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, `CLINE_DIR`,
  `GROK_HOME`, the `XDG_*` directories of opencode, the relocated `HOME` of
  cursor and antigravity) — made `@default` that profile: `ak usage` folded the
  CLI's own account into the profile's row (a container showed no `@default`
  for Claude or Codex), and `ak <cli> @default` launched the profile instead of
  the CLI's own home. Now `@default` always reads and runs the CLI's own home:
  such a variable (and an inherited `AGENTKIT_ACTIVE_PROFILE` for that CLI) is
  dropped for `@default` in launches, `ak profiles run`, `ak usage`, `ak pick`,
  `ak doctor` and `ak profiles`. A bare `ak <cli>` follows the documented
  precedence (`AGENTKIT_DEFAULT_PROFILE_<CLI>`, else `@default`) instead of
  inheriting the outer profile. A home moved outside ak's profile tree is still
  `@default`'s home. `ak capacity --self` keeps naming the running account from
  the variable.

## [1.0.0] - 2026-10-13

The first stable release. Interface stays **1**; no command, flag, key or
schema changes from 0.7.1.

### Stability commitment

From 1.0.0 on, the kit's public interface follows [Semantic
Versioning](https://semver.org/spec/v2.0.0.html): anything below changes
incompatibly only in a new major version, and additions arrive in minor
versions.

- **The command surface:** `ak <kind> [@profile]` for every kind in
  `providers.toml` (claude, codex, cursor, opencode, pi, cline, grok,
  antigravity and the glm, azure and xai routes), and the verbs `ak run`,
  `ak env`, `ak doctor`, `ak usage` (and `ak status`), `ak pick`,
  `ak capacity`, `ak lease`, `ak profiles`, `ak alias`, `ak install`,
  `ak setup` and `ak --skill`, with their documented flags (`ak --help`).
- **The permission posture:** autonomy by default, and an opt-out that always
  wins (`--ask`, `AGENTKIT_PERMISSIONS=ask`).
- **Interface 1:** the `ak doctor --json` shape, `ak env` and the `ak run`
  grammar and envelope, still reported as `"interface": 1`.
- **The JSON schemas:** `doctor-v1`, `usage-v1`, `pick-v1`, `capacity-v1`,
  `leases-v1`, `profiles-v1`, `setup-probe-v1` and `setup-verify-v1`
  (`docs/schema/`); a schema gains keys in place and changes incompatibly
  only under a new schema name.
- **The installed layout and the env file:** `install.sh` / `install.ps1`,
  the profile directories and the env-file variable names (`*_API_KEY` and
  their `_<SUFFIX>` per-profile forms).

### Changed

- **Version 1.0.0.** Every version source (`lib/common.py`, the three
  skills' metadata, the install and skill commands in the README and docs,
  the schemas' `$id`, the issue template) names 1.0.0, and `CONTRIBUTING.md`
  and `docs/doctor.md` describe the semver policy.
- **The README showcases the kit:** a pitch line, badges, a sample `ak usage`
  table, the eight supported coding agents with how each keeps accounts apart
  and what `ak usage` reads, and the provider routes (Z.AI GLM, Azure OpenAI,
  xAI, the Gemini API).
- Agent kit: the vendored DeepWorkPlan pack moves to 7.7.1 and the vendored
  herdr-peers skill to v1.0.0 (both pinned in `skills-lock.json`; herdr-peers
  checked against its release `SHA256SUMS`), and the addon registry
  (`.dwp/config.json`) records agentkit v1.0.0 and herdr v1.0.0.

## [0.7.1] - 2026-10-12

Interface stays **1**. Antigravity's API-key accounts sit with its Google
logins, and the kit's own agent kit is current.

### Added

- **The project logo.** `assets/logo-light.png` and `assets/logo-dark.png`
  (transparent, 1200×351); the README serves the one that matches GitHub's
  theme.
- **`ak status`** is another name for `ak usage`.
- **A named profile's suffixed credential variable is its login**
  (`GEMINI_API_KEY_WORK` for `@work`, any CLI's `[clis.<cli>.login] env`):
  `ak profiles`, `ak doctor`, `ak usage` and `ak pick` see such a profile as
  logged in (`token-var`).

### Changed

- **A Gemini API key is listed under Antigravity.** `GEMINI_API_KEY[_SUFFIX]`
  rows sit in the `antigravity` block (n/d, `GEMINI_API_KEY_WORK set`) instead
  of a block of their own, and a profile served by its key has that one row,
  not a second Google-login row. A profile without a key keeps its own login
  row (quota on Linux and in containers).
- **The Antigravity launch warning is per OS.** `ak antigravity @name` without
  `GEMINI_API_KEY_<SUFFIX>` warns about the machine-wide Google login only on
  macOS and Windows; on Linux and in containers the profile has a login of its
  own and nothing is shared.
- Agent kit: the vendored herdr-peers skill moves to v0.3.2 (pinned in
  `skills-lock.json`), and the addon registry (`.dwp/config.json`) records
  agentkit v0.7.1 and herdr v0.3.2.

## [0.7.0] - 2026-10-12

Interface stays **1**. Every account in `ak usage`, and Antigravity's quota:
the table lists each CLI's accounts whether or not their quota is readable,
and an Antigravity Google login shows the windows agy's own `/usage` panel
shows. `--json` and every schema are unchanged except for one additive
adapter id.

### Added

- **`ak usage` reads Antigravity.** A new `antigravity-quota` source: with the
  profile's Google login file (`antigravity-oauth-token` in agy's home — Linux
  and containers), two POSTs to agy's own Code Assist host (identifying as the
  Antigravity client, as agy does) give the account's
  plan (the Google AI subscription — `AI Pro`, `AI Ultra` — or `free`) and its quota summary, the one agy's
  own `/usage` panel shows: a five-hour and a weekly window for the Gemini
  models and for the Claude and GPT models (`5-hour Gemini  34%  in 1h 17m`). `ak pick` and `ak capacity`
  count such an account like any measured one. On macOS the login is a Keychain
  item in a format the kit does not parse: the row is `n/d`, `logged in`
  (`keychain_opaque`, presence only). The login file is also Antigravity's
  login probe now, so `ak profiles` and `ak doctor` see a container login.

### Changed

- **`ak usage` lists every account under its CLI.** Rows with no readable quota
  no longer fold into a closing `connected` block or an `n/d` line: each sits
  under its CLI's title like a measured one, `n/d` with how it is connected and
  the few-word reason, or `no login` with the command that logs it in. The
  table thus also says which accounts of every CLI are connected. `--json` is
  unchanged.
- Antigravity's profile note and docs say where its login lives per OS: a file
  per profile on Linux and in containers (sign in inside the profile), one
  OS-keyring slot per machine on macOS and Windows (use `GEMINI_API_KEY_<SUFFIX>`).

## [0.6.1] - 2026-10-12

Interface stays **1**. Patch: the four kit findings of the first live swarm
drill (a lead, lanes on three vendors, a capped handoff and a lead
succession, with no human keystroke).

### Fixed

- **`ak capacity --self` inside a Codex session.** Codex runs its tool
  shells from an app-server daemon that keeps the environment of whoever
  started it, so a Codex lane read "unknown account" (exit 3) and a capped
  lane could never hand off. An interactive `ak codex` that reuses a daemon
  running here now passes the account marker for the session
  (`-c shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT=…`, data:
  `providers.toml` `[clis.codex.daemon] marker`), and with no marker
  `--self` takes the account from a CLI home variable that names a profile
  directory inside `ak`'s own tree (`CODEX_HOME=<profiles>/codex/work1`).
  The default home, a folder outside the tree, or two candidates still exit
  3 — never a guess.
- **`ak pick --owner X` counted X's own leases as zero**, so a lead that
  leased each lane's account under its own address got an account it had
  already handed out. Every active lease now counts, the owner's own
  included; a Codex account is excluded for its own holder too; the new
  **`--reuse @profile`** (repeatable, needs `--owner`) hands the owner's own
  lease on (e.g. to a lane's successor).
- **Unknown-capacity kinds and one account per profile.** `ak capacity grok
  @default` was ambiguous (the grok login and an xAI key) while `ak lease
  grok @default` accepted it. `ak capacity`, `ak lease` and `ak pick` now
  resolve a kind + `@profile` to the same account: the named CLI's or
  provider's own row, else, for a kind served by a provider key, the
  provider's (`claude-glm @work` is `zai @work`); still ambiguous → exit 2
  naming the exact commands. `ak pick` offers each profile once. Every
  `pick-v1` candidate gains `verdict` (`ak capacity`'s rule; `unknown` for
  an account chosen with `--allow-unknown`), the document gains `reuse`
  (additive), and a refusal of only no-quota accounts names
  `--allow-unknown`.
- **Grok folder trust.** `ak grok … --trust-cwd` wrote nothing, yet Grok
  stops at "Do you trust the contents of this directory?". It now appends
  `[folders."<root>"] trusted = true` to Grok's `trusted_folders.toml`
  (format `grok-toml`), where `<root>` is the folder Grok asks about: the
  repository's main working tree — also from a linked worktree — or the
  launch folder outside a repository. An existing answer is left alone.
- Docs and skills: `docs/usage.md`, `docs/profiles.md` (Codex and its
  app-server daemon), `docs/permissions.md`, `docs/orchestration.md`,
  `docs/SECURITY.md`, and the `agentkit` and `agentkit-orchestrate` skills
  describe the above; the unattended reference says never to answer Grok's
  repository-level trust screen.

## [0.6.0] - 2026-10-12

Interface stays **1**. Capacity-aware agents: an agent can ask for its own
room at every task boundary, cheaply, and leads lease the accounts they hand
out. Every new surface is additive.

### Added

- **`ak capacity [<kind>] [@profile] [--self] [--low PCT] [--critical PCT]
  [--max-age S] [--json]`** — one account's headroom and a verdict (`ok`,
  `low`, `critical`, `unknown`), computed by `ak pick`'s own arithmetic so
  the two never disagree. Thresholds default to 25 / 10
  (`AGENTKIT_CAPACITY_LOW`, `AGENTKIT_CAPACITY_CRITICAL`). Exit 0 for every
  reading; `--self` exits 3 outside an `ak` launch (never a guess). Schema
  `capacity-v1`.
- **`AGENTKIT_ACTIVE_ACCOUNT=<kind>/@<profile>`** — set by every `ak` launch
  and `ak run`, `@default` included, for the CLI it starts (`ak capacity
  --self` reads it); a kind and a profile name only, never printed by
  `ak env`. `AGENTKIT_ACTIVE_PROFILE` is unchanged.
- **A usage cache** under the kit's state directory
  (`$XDG_STATE_HOME/agentkit/usage-cache/`, `AGENTKIT_STATE_DIR`): usage
  numbers only, `0600` files, atomic writes. `ak capacity` and `ak pick`
  reuse a reading younger than `--max-age` (300 s; `0` reads live) and write
  back what they read live; `ak usage` is the only command that always reads
  live, and it refreshes the cache.
- **`AGENTKIT_CAPACITY_CAP=[<kind-or-cli>]@profile=PCT[,…]`** — a
  lower-only drill cap (`min(real, cap)`, `"capped": true`) applied by
  `ak capacity` and `ak pick` (where a capped account below a `--need`
  percent no longer qualifies); a kind names the account its quota lives on;
  an invalid value or an unknown name exits 2.
- **`ak lease <kind> @profile --owner ADDR [--ttl DUR] [--purpose TEXT]`,
  `ak lease release …`, `ak lease ls [--json]`** — advisory, expiring
  account leases (schema `leases-v1`), changed under a portable lock and
  written atomically (`0600`). Codex takes one lease (`lease = "exclusive"`
  in `providers.toml`: one writer per `auth.json`); other accounts take many;
  only the owner releases.
- **`ak pick --owner ADDR`** skips Codex accounts leased to another owner and
  ranks by `headroom / (1 + other leases)`; **`--max-age S`**. `pick-v1`
  gains `owner` and, per candidate, `leases` and `capped` (additive). Without
  `--owner` the ranking is unchanged.
- Skills: `agentkit` teaches `ak capacity` and `ak lease`;
  `agentkit-orchestrate` gains **Capacity-aware lanes** (check at task
  boundaries with `ak capacity --self`, leases, proactive handoff) and states
  the account pool rule exactly: work moves only among accounts the developer
  declared for the work, within each vendor's terms; agents never create
  accounts, renew logins or spend a Codex reset.

### Changed

- `ak usage`, `ak pick` and `ak capacity` write the kit's usage cache (and
  nothing else); they still never write under a profile or the env file,
  refresh a login or spend a reset. `ak pick` reuses readings up to 300 s old
  by default (`--max-age 0` reads live).
- `ak profiles run` sets `AGENTKIT_ACTIVE_ACCOUNT` for its command too, so an
  inherited marker never names the outer account.

## [0.5.3] - 2026-10-12

Interface stays **1**. Patch: `ak codex` starts in a container whose Codex
home is shared with another machine.

### Fixed

- **Codex's app-server daemon in a shared home.** A Codex home shared with
  another machine (a host profile, or one volume shared by several
  containers) records a daemon installed by that machine, and Codex refused
  to start (`daemon executable not found`). An interactive `ak codex` now
  adds `--no-daemon` when the home records a daemon that is not on this
  machine or not built for its OS, and never when the daemon is present.
  `AGENTKIT_CODEX_NO_DAEMON=1` forces it. Declared as data
  (`[clis.codex.daemon]` in `providers.toml`).

### Added

- `ak doctor` reports each account's daemon state (`daemons`: `present`,
  `absent`, `missing` or `off`; additive in `doctor-v1`), and the text form
  says when `ak codex` adds `--no-daemon`.

## [0.5.2] - 2026-10-12

Interface stays **1**. A default profile per CLI, so a bare `ak claude` works
in a container whose host keeps Claude's login in the macOS Keychain.

### Added

- **`AGENTKIT_DEFAULT_PROFILE_<CLI>`** (environment or env file): the account
  a bare `ak <cli>`, `ak run <cli>` and `ak env <cli>` use. A positional
  `@profile`, `AGENTKIT_PROFILE` and an explicit `@default` (the CLI's own
  home) win. The profile must exist (a default never creates one); a
  provider kind (`claude-glm`) keeps the CLI's own home.
- **`pick`** as the value (opt-in, off by default): the account with the most
  headroom by `ak pick`'s policy among those whose login is portable (a file
  or a token variable, never a Keychain item); `@default` when none has room.
- `ak usage`, `ak pick` and `ak profiles --json` mark the default account
  (`"default": true`, additive in `usage-v1`, `pick-v1`, `profiles-v1`);
  `ak doctor` lists it (`default_profiles`, additive in `doctor-v1`) and
  names a default that does not exist.
- **`ak doctor` on Linux or in a container** names each account whose file
  names the account but whose login token is not there (a macOS Keychain
  login does not travel), with the fix.

## [0.5.1] - 2026-10-12

Interface stays **1**. Patch: a Cursor login on Linux is recognised, and
`ak profiles --json` reports where Claude's token really is.

### Fixed

- **Cursor login on Linux**: the default account keeps its login in
  `~/.config/cursor/auth.json` (not `~/.cursor/auth.json`), so `ak usage` and
  `ak doctor` reported `n/d` / `login: unknown` for a logged-in Cursor in a
  container or on a Linux host. The login probe now also reads the `xdg` root
  (`~/.config/cursor`); profiles are unchanged (`<profile>/home/.cursor`): a
  profile's HOME links the real `~/.config` in, so it never borrows the
  default account's login.
- **Claude login kind** (`ak profiles --json`, profiles-v1): an account with
  `.claude.json` (`oauthAccount`) was reported as a `file` login although that
  file only names the account; the token is `.credentials.json` or, on macOS,
  a Keychain item. The login is now `file` only with `.credentials.json`,
  `keychain` when the `Claude Code-credentials` item exists (a profile's own
  `-<sha256 prefix>` item for a profile), `none` when neither exists, and
  `unknown` when only the account file is there and the Keychain cannot be
  asked (`AGENTKIT_KEYCHAIN=off`). Presence only: the secret is never read.
  `@default` copied into a container without its token now reads `none`.
  The doctor's `logged_in` is unchanged.
- The bundled skills' versions and pinned install lines follow the release.

## [0.5.0] - 2026-10-11

Interface stays **1**. Accounts and quota for agents and humans: `ak pick`
chooses the account with room, the `agentkit-orchestrate` skill runs several
agents over several accounts and vendors, `ak profiles --json` and a Claude
login token per account let another host reuse the same accounts,
`--trust-cwd` lets new accounts start without the folder-trust screen, and
`ak usage` is redesigned. Antigravity is the eighth kind.

### Added

- **`--trust-cwd`** on `ak <kind>` and `ak run` (or `AGENTKIT_TRUST_CWD=1`,
  inherited by nested `ak`): marks the launch folder as trusted in that
  profile's Claude or Codex config before the CLI starts, so a new account
  does not stop at the folder-trust screen. Opt-in only. The orchestration
  skill documents unattended lanes (`references/unattended.md`): launch with
  no per-launch approval, the one keystroke a lead may send (folder trust of
  its own lane when `--trust-cwd` was unavailable), and escalation of every
  other screen. No agent answers Claude's bypass-permissions acknowledgement:
  the developer accepts it once per profile (the setup skill says so).
- **`ak profiles --json`** (schema `profiles-v1`, additive): every account
  by name — CLI, profile, path relative to the profiles root, isolation,
  login kind by presence and the key names that are set — with no value and
  no absolute path, so another host can recreate the same accounts.
- **A Claude login token per account**: `CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>`
  (from `claude setup-token`) logs a named Claude profile in;
  `ak claude @name`, `ak run` and `ak env` hand it to that profile as
  `CLAUDE_CODE_OAUTH_TOKEN`, never `@default`'s. `ak profiles` and
  `ak doctor` show it by name and count it as a login. Meant for containers
  that reuse the host's profiles (the macOS login lives in the Keychain).
- **`ak pick`**: the account(s) with the most usable headroom for a kind,
  from the same rows as `ak usage` and equally read-only (no login refreshed,
  no reset spent). One documented policy: `ok` rows only, model-scoped
  windows only with `--model`, a reserve on windows of 7 days or more
  (`--reserve`, default 10), `--need WIN:PCT`, `--count N` for parallel
  work, `--exclude`, `--allow-unknown`. Exit 0 chosen, 1 none qualifies
  (the soonest reset is named), 2 usage, 3 nothing matches. `--json` is the
  new additive schema `pick-v1` (`docs/schema/pick-v1.json`); interface 1
  and `usage-v1` are unchanged.
- **`agentkit` skill references**: `references/accounts.md` (the account
  model, lifecycle, keys by name, platforms) and `references/usage.md`
  (reading the table, an action per status, plan-specific windows,
  `ak pick`), loaded only when the task needs them.
- **`agentkit-orchestrate` skill** (`ak --skill orchestrate`): several agents
  over several accounts and vendors — inventory once per batch,
  `ak pick --count`, one worktree per writing delegate, `ak run`, failover,
  verification and a spend report.
- **Docs**: [Accounts](docs/accounts.md) (the account model end to end),
  [Orchestration](docs/orchestration.md) (the loop, patterns, failover,
  Herdr lanes, Deep Work Plans, safety), and "Reading the table" and
  "Choosing an account" in [`ak usage`](docs/usage.md).

- **Antigravity CLI (`ak antigravity`)**: Google's `agy` as the eighth kind.
  Autonomy is `--dangerously-skip-permissions`; `-c` is `--continue`,
  `-r <id>` is `--conversation <id>` (agy has no picker, so `-r` alone is a
  usage error that says so); `ak run antigravity` runs `agy -p` and reads
  `response` (or `error`) from its JSON. `ak install antigravity` installs the
  pinned `1.3.3` tarball (sha256 recorded from downloads checked against the
  sha512 of Google's release manifest). The `classic` alias preset gains
  `agyx`.
- **Antigravity profiles**: a profile is a `HOME` of its own (new
  `isolation = "home"`, with the rest of the real HOME linked in, as Cursor).
  agy keeps its Google login in one OS-keyring slot per machine, so a
  profile's own account is its key, `GEMINI_API_KEY_<SUFFIX>` (new `gemini`
  provider, key optional like `grok`): with it `ak` writes
  `"modelProvider": "gemini"` into that home's `settings.json`, and removes it
  when the key is gone (agy refuses to start with the field and no key). The
  value is never written. `ak profiles add antigravity @name` explains this.
- `ak usage` lists Antigravity and a Gemini key as `n/d` (no readable quota).

### Changed

- `ak` (the kinds list) sizes its columns to the longest kind and CLI name,
  and names a CLI's command when it differs: `antigravity (agy)`, `cursor (agent)`.
- A CLI's command names its kind everywhere a kind or CLI is expected: `ak agy`
  is `ak antigravity`, `ak agent` / `ak cursor-agent` is `ak cursor` (also in
  `ak run`, `ak env`, `ak usage`, `ak profiles`, `ak alias add`, `ak install`).

- **`ak usage` lists connected accounts it cannot measure.** Cursor, Grok,
  Antigravity, xAI and the like have no quota to read, but an account with a
  login (or its key) is still shown, in a closing `connected` block that says
  how it is connected (`logged in`, `XAI_API_KEY set`); only the rest fold
  into the `n/d` line. `--json` rows gain the optional `connected` key.
- **Keychain logins are detected.** `login.keychain` in `providers.toml`
  names a CLI's macOS Keychain item (Cursor, Antigravity); `ak doctor` and
  `ak usage` ask only whether it exists — `security` without `-w`, the
  secret is never returned. `AGENTKIT_KEYCHAIN=off` skips it (the test suite
  sets it, so it never touches a real Keychain).
- **`ak doctor`**: the CLI column fits the longest name, and a provider key
  shows `set` only when the key itself is set (an optional-key kind logged in
  through its CLI no longer reads as a set key).
- **`ak usage` groups by CLI.** One block per CLI or provider, with a title
  line (`claude · Claude Code`), its accounts indented under one shared
  header and a blank line between blocks; the CLI id is no longer repeated
  on every row, and the Codex reset tip is said once per block.
- **`ak usage` fits the terminal.** A row with a problem shows its status and
  a few-word note (`log in: ak claude @work`) starting under USED; the
  accounts with no readable quota fold into one closing `n/d` line grouped by
  cause; nothing wraps, and a note too long for the width ends in `…`.
  `-v`/`--verbose` lists every row with its full reason. Pipes, files and
  `--json` are unchanged (the `usage-v1` rows carry no new key).
- **Claude Code: per-model weekly windows.** A plan without a global weekly
  cap (Team) reports its weekly limits per model in the endpoint's newer
  `limits` list; `ak usage` now shows them. Every Claude window is its own
  line with an unambiguous label: `5-hour`, `7-day all models`,
  `7-day <model> only` (window ids are unchanged).
- **Claude Code: per-profile Keychain logins on macOS.** A profile without a
  `.credentials.json` is read from its own Keychain item,
  `Claude Code-credentials-<first 8 hex of sha256(profile directory)>`, the
  name Claude Code derives; a default home moved by `CLAUDE_CONFIG_DIR` uses
  the same rule. Before, such a profile was reported `no_login`.
- **Codex: limit resets.** The limit resets a ChatGPT account holds (the ones
  Codex spends with `/usage`) show as a `resets  3 available` line, and as the
  optional row key `resets_available` in `--json` (additive; `usage-v1`
  documents it).
- **Z.AI: named windows and credits.** The two `CREDIT_LIMIT` entries of a
  coding plan were shown as `Credits` and `Credits (2)`; their `unit` +
  `number` now name them `5-hour` and `7-day` (window ids `5h`, `7d`), and the
  credits used out of the limit show next to the reset (`35.22K/60K`; `-v`
  adds the unit). `--json` windows gain the optional keys `used`, `limit` and
  `unit` (additive; `usage-v1` documents them).
- **`ak doctor`**: the "Provider kinds" section is one line per key with the
  kinds it serves (an unset key no longer prints one "not ready" line per
  kind). `ak doctor --json` is unchanged.
- `providers.toml` usage tables accept `short` (the table note of an
  `unsupported` source) and `keychain_profile`.

### Fixed

- **`ak usage` bars show small numbers**: 4% drew an empty bar and 14% looked
  like 10%. The bar keeps its ten cells, with eighth-cell precision on UTF-8;
  any nonzero use shows at least one mark, and only 100% is full (ASCII:
  whole `#` cells, same rule).
- The fake usage endpoint of the test suite accepts the 8 parallel
  connections `ak usage` opens; its default listen backlog of 5 made macOS
  refuse some, which showed up as a flaky scenario check.

## [0.4.0] - 2026-10-10

Interface stays **1**. `ak usage`, and the `agentkit-setup` skill with `ak setup`.

### Added

- **`ak usage [<kind-or-cli>] [@profile] [--json] [--timeout SECONDS] [--no-color]`**:
  the quota and usage of every account, one row per credential identity, in
  one table. Live for Claude Code subscriptions (5-hour, weekly and per-model
  windows), Codex ChatGPT logins (session, weekly and named limits) and the
  Z.AI coding plan (one row per key, shared by the `*-glm` kinds); Cursor, Grok,
  xAI and Azure OpenAI are `n/d` with their reason, and OpenCode, Pi and Cline
  report through the provider behind each kind. Rows are fetched in parallel
  and a failing row never hides the others. Read-only: it never refreshes a
  login, prints a token or writes under a profile. The endpoints are
  vendor-internal and unofficial. Works the same on Linux, macOS and Windows.
- **`usage-v1` JSON schema** (`docs/schema/usage-v1.json`): an additive,
  versioned surface; interface 1 and `doctor-v1` are unchanged.
- **`[clis.<cli>.usage]` / `[providers.<id>.usage]` tables** in `providers.toml`
  with a closed, validated key set (https only, `{token}` only in header values).
- Tests: the `usage` and `usage-providers` scopes, bash-free checks that run
  natively on Windows in CI, and a loopback fake endpoint.
- **`agentkit-setup` skill and `ak setup probe | verify | docker`**: a configurator an agent follows to install,
  configure, verify, repair and upgrade the kit on macOS, Linux, WSL, Windows and in containers. The skill asks
  before each system package, shell rc edit, autonomy choice, profile, CLI install, repository write and uninstall,
  and handles provider keys by name only. The helper is read-only and works from an uninstalled clone: `probe`
  reports the machine (OS, arch, libc, container/CI/WSL, tools, existing install, env file, profiles, a posture
  hint), `verify` returns ordered checks each with the exact repair command, and `docker` renders a Dockerfile,
  compose file, entrypoint or devcontainer snippet that pins a release tag, verifies the tarball's SHA256 before
  unpacking, runs as a non-root user and keeps keys out of the image. `ak --skill setup` prints the skill. JSON
  schemas `setup-probe-v1` and `setup-verify-v1` are additive; interface 1 is unchanged.
- Tests: the `setup` and `setup-skill` scopes, bash-free checks that run natively on Windows in CI, the skill's
  documented flows executed in sandboxes (with deliberate drifts that must fail), and an opt-in
  `setup-docker-live` scope plus a `docker recipe builds` CI job.

### Security

- `ak setup` and the setup skill: read-only helper commands, a recipe renderer that refuses to print an unsafe
  recipe, tag-and-digest-only install sources and consent gates; see `docs/SECURITY.md`.
- `ak usage` is the first command that reads login content and queries a
  vendor on your behalf. See `docs/SECURITY.md`, "Quota queries": fixed https
  hosts, no redirect, loopback-only override, no refresh, no write, planted-secret
  tests. The "no network except `ak install`" statement now names `ak usage`.

## [0.3.0] - 2026-10-09

Interface stays **1**. The `providers` alias preset.

### Added

- **`providers` alias preset** (`ak alias preset providers --on`): one
  shortcut per provider kind under the kind's own name (`claude-glm`,
  `codex-glm`, `codex-azure`, `codex-xai`, `opencode-*`, `pi-*`,
  `cline-*`), each a plain `ak <kind>` that follows the permission posture.
  The names carry a dash, so they are defined only for bash and zsh.
  `ak doctor --json` gains `aliases.providers` (additive; interface 1).

## [0.2.2] - 2026-10-09

Interface stays **1**. Security fix to the 0.2.1 `ak env import` hardening.

### Fixed

- **`ak env import` could still import shell code** (a fix to the 0.2.1
  hardening): a single quote inside a double-quoted value ended the
  re-quoted word, so `Q="a'; touch x; '"` ran when the env file was next
  sourced. Values with a quote are refused in every form, a second guard
  refuses to write one, and the source path in the header comment is
  printable-only. A failed tarball swap now puts the previous version back.

## [0.2.1] - 2026-10-09

Interface stays **1**. Security fixes from the v0.2.0 review: the opt-out always wins.

### Fixed

- **An inherited opt-out could be lost.** A nested `ak` re-reads the env
  file, and an `AGENTKIT_PERMISSIONS=auto` line there (the v0.1 opt-in)
  replaced the `AGENTKIT_PERMISSIONS=ask` its parent passed on, so a
  sub-agent of an opted-out agent ran with autonomy. The inherited `ask`
  now outranks the file, in the bash launcher and the python core.
- **The opt-out now also wins over an explicit `--auto`**, so an alias or an
  agent that types `--auto` cannot bypass `AGENTKIT_PERMISSIONS=ask`.
- **`ak env import` imports plain data only.** Values a shell would
  interpret (`$(…)`, backquotes, `$`, `;`, `&`, `|`) were copied into the
  sourced env file; they are now skipped and reported, and imported values
  are written as single-quoted literals.
- **`ak install cursor` no longer replaces a foreign `~/.local/bin/agent`**
  (or `cursor-agent`): only a missing path or a link into the kit's own
  versions directory is replaced; anything else is left alone and reported.
  A reinstall keeps the previous tree until the new one is in place.

## [0.2.0] - 2026-10-09

Interface stays **1**. Autonomy by default (breaking behaviour), verified CLI installs, `ak env import`.

### Changed — breaking behaviour (interface stays 1)

- **Autonomy is the default.** Every launch (interactive, `ak run`, profiles,
  the `classic` preset and custom aliases) adds the CLI's own autonomy flag
  from `providers.toml`. Opt out with `--ask` on a launch or
  `AGENTKIT_PERMISSIONS=ask`; the opt-out always wins and is passed on to
  nested launches. `--ask` with `--auto` is a usage error. Autonomy is meant
  for disposable or sandboxed environments; `ak doctor` warns when it is on
  outside a container. The `classic` preset becomes plain name shortcuts for
  `ak <kind>`; custom aliases accept `--ask` or `--auto`. The doctor JSON
  shape is unchanged: `permissions` now reports `auto` when unset.
- **`ak install` verifies every CLI before anything runs.** Channels are
  `binary`, `tarball` and `npm`; every CLI is pinned to an exact version with
  a per-platform sha256 (claude from the vendor manifest; cursor and grok
  recorded on first use) or the npm registry `integrity`. A mismatch or an
  unpinned platform refuses the install and leaves nothing behind; archives
  are unpacked only when every entry stays inside its directory. Vendor
  install scripts are no longer run (the `script` channel and the
  `unpinned` key are retired). Cursor is pinned to `2026.10.01-e373342` and
  Grok to `1.0.50`, both previously unpinned. `scripts/update-pins.sh`
  re-derives every digest from its source.

### Added

- `ak env import <file>`: copies `KEY=value` lines from another env file
  into the kit's env file. It never overwrites a key and never prints a
  value, refuses a source others can write, skips shell code and empty
  values, keeps profile-suffixed keys, and keeps the destination mode 600.
- Public repository standard: `CONTRIBUTING.md`, `SECURITY.md` (policy),
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), issue and pull request
  templates, `CODEOWNERS`, Dependabot for GitHub Actions, `CLAUDE.md` →
  `AGENTS.md`.
- `scripts/check-public-hygiene.sh`: CI check that no tracked file carries
  private context or secret-shaped strings (allowlist for visibly fake
  fixtures in `.public-hygiene-allow`).
- Release workflow: an annotated `vX.Y.Z` tag publishes the GitHub release
  with the changelog section, the source tarball and `SHA256SUMS`.

### Changed

- README follows the ecosystem's standard section order; documentation
  examples use `$HOME` instead of a sample user path.

## [0.1.1] - 2026-10-08

Security release. **Interface 1** (unchanged). Upgrade from 0.1.0.

### Security

- **Profile writes could follow a symlink planted inside a profile**
  (medium; affects `0.1.0`). `ak profiles hooks`, and provider config
  writers when launching a profile, wrote through symlinks: a process able to
  write inside a profile directory (for example an agent running in it) could
  plant `<profile>/settings.json -> ~/.claude/settings.json` or a hook file
  pointing at a shell rc, and the next `ak profiles hooks` (or provider launch
  of that profile) wrote outside the profile. Hooks now refuse symlinked
  destinations and confine every write to the profile; provider writers
  confine writes to the profile when one is used (symlinks in the CLI's own
  home, e.g. a dotfiles-managed config, are still followed). Regression
  checks in the `security` test scope.
- Windows: programs that call ak must start the python core directly
  (`py -3 <install>\lib\ak.py …`), not `ak.cmd`, whose arguments `cmd.exe`
  re-parses; now stated in the skill and `docs/run.md`. The set of
  characters refused for batch-file targets now also covers `(`, `)` and
  line breaks.

Found by an independent review of the 0.1.0 release (the verification pass
of its pre-release fixes).

## [0.1.0] - 2026-10-08

First public release. **Interface 1.**

### Added

- `ak` / `agentkit`: one command surface for seven terminal coding agents —
  `claude`, `codex`, `cursor` (Cursor's `agent`, never Grok's), `opencode`,
  `pi`, `cline`, `grok` — and their provider variants `claude-glm`,
  `codex-{glm,azure,xai}`, `opencode-{glm,azure,xai}`, `pi-{glm,azure,xai}`,
  `cline-{azure,xai}`. Kinds are data in `providers.toml`.
- The same session flags everywhere (`-c`, `-r [id]`, `-l`) mapped to each
  CLI's own form; `--` passes everything through; `ak` exec's the CLI.
- Profiles: several accounts per CLI (`ak claude @work`), isolated per CLI
  under `~/.local/share/agentkit/profiles` (mode 700), per-profile provider
  keys `<KEY>_<SUFFIX>` with no fallback, and `ak profiles
  ls|add|path|run|rm|hooks`.
- Permissions posture: pass-through by default; `--auto` or
  `AGENTKIT_PERMISSIONS=auto` adds the CLI's own autonomy flag, never
  inherited by the agents a session starts.
- `ak run`: headless runs with a frozen per-CLI mapping, exit codes
  0/1/2/3/4/5/≥64, process-tree kill on timeout and cancellation, and one
  JSON envelope with `--output-format json`.
- `ak env`: a profile's environment as `KEY=VALUE` lines (no secrets) for
  launchers such as Herdr.
- `ak doctor [--json]`: CLIs, logins (file presence), profiles, key names,
  posture, aliases and Herdr hooks; JSON schema `docs/schema/doctor-v1.json`.
- `ak install`: missing CLIs from each vendor's official channel, pinned
  where the vendor allows it, never piped from the network into a shell.
- `ak alias` with a guarded shell rc block, and the `classic` preset
  (`claudex`, `codexx`, `cursorx`, `opencodex`, `pix`, `clinex`, `grokx` =
  `ak <kind> --auto`), **off** by default.
- `ak profiles hooks`: copies Herdr's agent-state hooks into a profile.
- Installers: `install.sh` (macOS, Linux, WSL; `--no-rc`, `--uninstall`)
  and `install.ps1` (Windows, native python core via `ak.cmd`).
- The `agentkit` skill (`skills/agentkit/SKILL.md`, printed by `ak --skill`).
- Test suite (`bash tests/run.sh`): sandbox HOME, fake CLIs, no network;
  CI on ubuntu, macOS, python 3.9 and Windows.

### Security

- Provider keys are never printed, logged or written by the kit; config
  writers store references only. Documented exception: Cline takes its key
  on the command line. See `docs/SECURITY.md`.
- A group- or world-writable env file is refused (it is sourced as shell).

### Credits

Redesigned from the author's earlier coding-agents-setup-kit (wrappers,
installers, provider writers) and profile work; see `CREDITS.md`.

[Unreleased]: https://github.com/DailybotHQ/coding-agents-kit/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/DailybotHQ/coding-agents-kit/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.7.1...v1.0.0
[0.7.1]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/DailybotHQ/coding-agents-kit/compare/v0.5.3...v0.6.0
[0.5.1]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.5.1
[0.5.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.5.0
[0.4.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.4.0
[0.3.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.3.0
[0.2.2]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.2
[0.2.1]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.1
[0.2.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.2.0
[0.1.1]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.1.1
[0.1.0]: https://github.com/DailybotHQ/coding-agents-kit/releases/tag/v0.1.0
