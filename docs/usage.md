# `ak usage` — quota and usage of every account

```
ak usage [<kind-or-cli>] [@profile] [-v | --verbose] [--json] [--timeout SECONDS] [--no-color]
```

One command, one list: the quota windows of every account the kit can see —
each profile of each CLI — so you know which account has room before you
start a long task. It is a list, not a dashboard: no graphics, no daemon, no
cache, and **read-only** (it never refreshes a login, never prints a token and
never writes under a profile or the env file).

```text
  PROFILE   PLAN             WINDOW            USED             RESET

claude · Claude Code
  @default  max              5-hour            ████░░░░░░  42%  in 2h 14m
                             7-day all models  █░░░░░░░░░  13%  in 4d 1h
                             7-day Fable only  ███░░░░░░░  31%  in 4d 1h
  @work     team             5-hour            ██████████  97%  in 38m
                             7-day Fable only  ███████░░░  70%  in 1d 3h
  @old      -                expired           open ak claude @old once to renew

codex   resets: use one with /usage in codex
  @default  plus             5-hour            ████░░░░░░  35%  in 1h 20m
                             7-day             █░░░░░░░░░  14%  in 4d 9h
                             resets            3 available

zai · Z.AI GLM Coding Plan
  @default  pro              5-hour            ███░░░░░░░  27%  in 3h 28m  3.27K/12K
                             7-day             ██████░░░░  58%  in 5d 4h   35.22K/60K

connected · no quota to read
  grok         @default  logged in        per-session only
  antigravity  @default  logged in        no quota source
  xai          @default  XAI_API_KEY set  needs a management key

n/d  cursor (web session only) · opencode, pi, cline (via a provider key)
     ak usage -v for every row and its reason
```

One block per CLI or provider: its id and name on a title line, its
accounts indented under one shared header, a blank line between blocks. A
tip that applies to the whole block (how to spend a Codex reset) is said
once, on the title line.

An account with no quota to read still matters when it is **connected**: a
login found for it (a login file, a credential variable, or — on macOS, for
the CLI's default home — its Keychain item, of which only the presence is
asked) or its provider key set. Those close the table in a `connected` block
that says how each is connected; the rest fold into the `n/d` line. In
`--json` such a row carries `"connected": true` (or `false`; the key is
absent when it cannot be told).

On a terminal the table fits its width: a row with a problem shows its status
and a few-word note (`log in: ak claude @work`), and the accounts with no
readable quota fold into one closing `n/d` line grouped by cause. Nothing
wraps; a note too long for the width ends in `…`. `-v` lists every row with
its full note instead. A pipe or a file gets the whole text (no width).

## Reading the table

A real table with several Claude accounts on two plans, a Codex account with
resets, a Z.AI coding plan and two connected accounts (profile names are
generic):

```text
  PROFILE   PLAN  WINDOW            USED             RESET
claude · Claude Code
  @default  max   5-hour            █░░░░░░░░░  10%  in 1h 38m
                  7-day all models  ████████░░  80%  in 1d 22h
                  7-day Fable only  ░░░░░░░░░░   0%  in 1d 22h
  @team    team  5-hour            ░░░░░░░░░░   0%  in 4h 8m
                  7-day all models  ██░░░░░░░░  24%  in 3d 3h
                  7-day Fable only  █░░░░░░░░░  11%  in 3d 3h
  @work1    team  5-hour            █░░░░░░░░░  10%  in 38m
                  7-day Fable only  ░░░░░░░░░░   0%  in 1h 28m
codex   resets: use one with /usage in codex
  @default  plus  5-hour            ░░░░░░░░░░   0%  in 4h 59m
                  7-day             ░░░░░░░░░░   0%  in 6d 23h
                  resets            3 available
zai · Z.AI GLM Coding Plan
  @default  pro   5-hour            ████░░░░░░  36%  in 1h 51m  4.36K/12K
                  7-day             ██████░░░░  60%  in 5d 3h   36.31K/60K
connected · no quota to read
  cursor       @default  logged in        web session only
  xai          @default  XAI_API_KEY set  needs a management key
```

| Column | What it says |
| --- | --- |
| PROFILE | the account: `@default` is the CLI's own home, `@name` a profile ([Accounts](accounts.md)). Shown once; the lines under it belong to the same account |
| PLAN | the vendor's own plan label (`max`, `team`, `plus`, `pro`); `-` when not reported |
| WINDOW | one of the vendor's own limits: `5-hour` (the short rolling window), `7-day all models` (the weekly cap), `7-day Fable only` (a weekly cap that counts one model) |
| USED | percent of that window already used, as a bar and a number; the room left is 100 minus it |
| RESET | when that window starts over; after it, Z.AI shows the credits used out of the limit |

What the example says:

- **Plans differ in their windows.** `@default` (Max) has a global weekly
  cap and is at 80% of it: room for a short task, not a long one. `@team`
  and `@work1` are on Team. `@work1` has no global weekly cap at all: only
  the 5-hour window and a model-only weekly window, so work that does not
  use that model is bounded by the 5-hour window alone.
- **Model-only windows** (`7-day Fable only`) limit work on that model only.
- **Resets** (`codex … resets  3 available`) are not a window: they are the
  limit resets the account holds. Only you spend one, with `/usage` inside
  Codex; the kit never does, and the title line says how.
- **Credits** (`zai`): Z.AI reports absolute credits; `4.36K/12K` is used
  out of the limit. Its 5-hour window has 64% left, its week 40%: the week
  binds.
- **The `connected` block** lists accounts with no quota to read that work
  anyway: a login found (`logged in`) or a provider key set
  (`XAI_API_KEY set`). Their headroom is unknown.
- **The `n/d` line** (absent here) folds the accounts with no readable quota
  and no connection, grouped by cause; `ak usage -v` shows each with its
  reason.

## What it shows

One **row per credential identity**, not per kind: `claude-glm @2` and
`codex-glm @2` read the same Z.AI key, so they are one `zai @2` row that lists
the kinds sharing it. Each row carries the provider's **own windows** (5-hour,
weekly, per model, tokens, MCP, …); `ak` never merges them into an invented
quota. No account identity (e-mail, organisation, id) is read or shown.

Rows appear for: the CLI's own home (`@default`) when the CLI is installed,
every profile directory, and every provider key that is set (`ZAI_CODING_API_KEY`
and `ZAI_CODING_API_KEY_<SUFFIX>`). A provider with no key set has no row.
Order: the CLI order of `providers.toml`, then `@default`, then profile names.

| Source | Where the number comes from | Notes |
| --- | --- | --- |
| Claude Code subscription | `api.anthropic.com` usage endpoint, with the profile's login (`.credentials.json`; on macOS the profile's Keychain item) | needs the `user:profile` permission; a plan without a global weekly cap (Team) shows its per-model weekly windows only; each window is its own line: `5-hour`, `7-day all models`, `7-day <model> only` |
| Codex (ChatGPT login) | `chatgpt.com` usage endpoint, with the profile's `auth.json` | an API-key login has no quota: `n/d`; the limit resets the account holds show as a `resets` line (`resets_available` in `--json`) |
| Z.AI coding plan | `api.z.ai` quota endpoint, with the profile's `ZAI_CODING_API_KEY[_SUFFIX]` | global host only; the windows are named by their period (`5-hour`, `7-day`) and show the credits used out of the limit |
| Cursor, Grok, Antigravity, xAI, Azure OpenAI, Gemini API | — | `n/d` with the reason (browser session only, per-session usage only, needs a management key, nothing to read) |
| OpenCode, Pi, Cline | the provider behind the kind (`opencode-glm` → Z.AI, `pi-xai` → xAI) | an `n/d` row only when no provider key covers the profile |

**These endpoints are vendor-internal and unofficial.** They can change
without notice; when one does, that row says `error: unexpected response
shape` and the rest of the list is unaffected.

## Options

| | |
| --- | --- |
| `<kind-or-cli>` | only the rows of a CLI (`claude`), a kind (`claude-glm` selects the Z.AI rows) or a provider (`zai`) |
| `@profile` | only that profile (`@default` and `@1` are the CLI's own home) |
| `-v`, `--verbose` | one line per row, n/d rows included, with the full reason or error |
| `--json` | exactly one JSON object, schema `usage-v1` ([`schema/usage-v1.json`](schema/usage-v1.json)), no ANSI |
| `--timeout SECONDS` | per request, 1-60 (default 10) |
| `--no-color` | and `NO_COLOR`; colour is also off when stdout is not a terminal |

Rows are fetched in parallel (at most 8 at once); one slow or failing row does
not delay or hide the others.

## Statuses and exit codes

| Status | Meaning | What to do |
| --- | --- | --- |
| `ok` | the windows are the provider's current numbers | — |
| `expired` | the login is past its own expiry (no request is made) | open that profile once; its CLI renews the login |
| `no_login` | no readable login for that profile (the message says why) | log in as that profile (`ak profiles run <cli> @name -- <login command>`) |
| `no_scope` | the login lacks the permission, or was rejected (HTTP 401/403) | sign in again with a full login |
| `rate_limited` | the endpoint answered HTTP 429 | retry later |
| `unsupported` | `n/d`: there is no readable quota; the reason is on the row | — |
| `error` | network failure, timeout, HTTP error, or a response of an unexpected shape | the message is one line and never holds a secret |

| Exit | Meaning |
| --- | --- |
| 0 | every row is `ok` or `unsupported` |
| 1 | at least one row is `expired`, `no_login`, `no_scope`, `rate_limited` or `error` |
| 2 | usage error (unknown option, unknown kind, bad `--timeout`) |
| 3 | nothing to report for that filter |
| ≥ 64 | kit internal error |

## For programs

`ak usage --json` is a versioned, **additive** surface: `"schema": "usage-v1"`
and `"interface": 1`. Interface 1 (`ak doctor --json`, `ak env`, `ak run`) is
unchanged. Check `schema` before reading anything else; new top-level keys may
appear in later minor versions. On Windows a program starts the core directly:
`py -3 <install>\lib\ak.py usage --json` (as with `ak run`; `ak.cmd` is for
typing at a prompt).

```json
{"schema": "usage-v1", "interface": 1, "generated_at": "2026-10-10T12:00:00Z", "rows": [
 {"cli": "claude", "profile": "@default", "kinds": ["claude"], "plan": "max", "status": "ok",
  "source": "anthropic-oauth", "error": null, "reason": null,
  "windows": [{"id": "5h", "label": "5-hour", "used_pct": 42, "resets_at": "2026-10-10T17:00:00Z", "window_seconds": 18000}]}]}
```

## Choosing an account

```
ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT]
        [--count N] [--exclude @profile]... [--allow-unknown] [--json] [--timeout SECONDS]
```

`ak pick` reads the same rows as `ak usage` — same enumeration, filter and
parallel requests, equally **read-only** (no login is refreshed, no reset is
spent, nothing is written) — and returns the account with the most usable
room for a kind. `<kind-or-cli>` resolves as in `ak usage` (`claude-glm`
selects the Z.AI rows); `@profile` turns it into a check of one account.

The policy, in plain words:

1. **Only `ok` rows are eligible.** `expired`, `no_login`, `no_scope`,
   `rate_limited` and `error` rows are left out with that status as the
   reason. `unsupported` rows are left out (`no readable quota`) unless
   `--allow-unknown`, which admits the connected ones after every measured
   account.
2. **Which windows count.** Every window without a model scope (`5h`, `7d`,
   the provider's windows). A model-only window (`7d-<model>`) counts only
   when `--model` names that model. So without `--model`, a Team account
   with no global weekly cap is bounded by its 5-hour window.
3. **A window whose reset has passed** counts as unused.
4. **A reserve on long windows.** Windows of 7 days or more keep
   `--reserve` percent unused (default 10): a long window's free room is
   `100 − reserve − used`. The 5-hour window keeps no reserve. A window with
   unknown usage makes the headroom unknown.
5. **Headroom** is the smallest free room over the windows that count; that
   window is the **binding** one. `--need WIN:PCT` also requires `PCT`
   percent free in the window whose id is exactly `WIN` (`5h`, `7d`,
   `7d-fable`); an account without that window does not qualify.
6. **Ranking.** Most headroom first; on a tie, the account whose long window
   resets first (room that resets soon is lost if unused); then the order of
   `providers.toml` and the profiles (`@default` first). Resets available
   never count as headroom.

| Option | |
| --- | --- |
| `--model NAME` | model-scoped weekly windows of that model also count (`fable`, `opus`, …) |
| `--need WIN:PCT` | the window `WIN` must keep `PCT`% free (1-100); repeatable |
| `--reserve PCT` | percent kept unused on windows of 7 days or more (0-50, default 10) |
| `--count N` | up to N distinct accounts, best first (1-16, default 1); a warning when fewer qualify |
| `--exclude @name` | leave an account out (repeatable), e.g. one already busy |
| `--allow-unknown` | connected accounts with no readable quota may be chosen, last |
| `--json` | one object, schema `pick-v1` ([`schema/pick-v1.json`](schema/pick-v1.json)) |
| `--timeout SECONDS` | per request, as `ak usage` |

The text output is one line per chosen account:

```text
claude @work2  headroom 100%  binding 5h  resets in 3h 48m
```

| Exit | Meaning |
| --- | --- |
| 0 | at least one account chosen |
| 1 | no account qualifies; stderr gives the reasons and the soonest reset among the measured accounts |
| 2 | usage error |
| 3 | nothing matches the filter (no profile or login) |
| ≥ 64 | kit internal error |

### Worked examples

The example table above, plus two more Claude Team accounts, `@work2` and
`@work3` (5-hour 0%, 7-day Fable only 0%, resetting in 18h 28m and 2d 13h),
and four Codex accounts, all at 0%, whose 7-day windows reset in 6d 20h
(`@work1`), 6d 23h (`@default`, `@work2`) and 7d 0h (`@work3`). Reserve 10%.

| # | Command | Result | Why |
| --- | --- | --- | --- |
| E1 | `ak pick claude` | `@work2`, headroom 100 | default 10 (90−80), team 66 (90−24), work1 90, work2 and work3 100 (no weekly cap counts); tie → profile order |
| E2 | `ak pick claude --model fable` | `@work1` | the Fable window now counts, with its reserve: work1, work2, work3 all 90; tie → work1's Fable window resets first |
| E3 | `ak pick claude --count 3` | `@work2`, `@work3`, `@work1` | 100, 100, 90; team (66) and default (10) rank after |
| E4 | `ak pick claude --need 7d:30` | `@team` | only default and team report `7d`: default has 10 free, team 66 |
| E5 | `ak pick claude-glm` | `zai @default`, headroom 30 | 5-hour 64 free, 7-day 90−60 = 30; binding `7d` |
| E6 | `ak pick codex` | `@work1` | all four at 90 (the 7-day reserve binds); tie → earliest 7-day reset; resets never count |
| E7 | `ak pick cursor` | exit 1, `no readable quota` | connected only; with `--allow-unknown` → `@default`, headroom unknown |
| E8 | `ak pick claude @default --need 5h:95` | exit 1 | 5-hour free 90 < 95; stderr names the soonest reset |

### `pick-v1`

`ak pick --json` is a versioned, additive surface like `usage-v1`: check
`schema` before reading anything else. `chosen[]` holds the accounts picked;
`candidates[]` every evaluated row, eligible ones first, each excluded one
with its `excluded_reason`.

```json
{"schema": "pick-v1", "interface": 1, "generated_at": "2026-10-11T12:00:00Z",
 "target": "claude-glm", "model": null, "reserve_pct": 10, "need": [], "count": 1,
 "chosen": [{"cli": "zai", "profile": "@default", "kinds": ["claude-glm", "codex-glm"], "status": "ok",
   "eligible": true, "headroom_pct": 30, "binding_window": "7d",
   "resets_at": "2026-10-16T15:00:00Z", "excluded_reason": null}],
 "candidates": ["… the same object, then every other evaluated row …"],
 "soonest_reset": "2026-10-16T15:00:00Z"}
```

Run it once before a batch of work, never in a loop: each call asks every
vendor, as `ak usage` does. Using several accounts at once:
[Orchestration](orchestration.md).

## Windows, macOS and Linux

One code path everywhere; only where a login lives differs.

| Login | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Claude Code | `.credentials.json` in the config directory | a file if there is one, else the Keychain item: `Claude Code-credentials` for the default home, `Claude Code-credentials-<8 hex>` for a profile (the first 8 hex of the sha256 of its directory, the name Claude Code derives) | the file in `%USERPROFILE%\.claude` (or the profile) |
| Codex | `auth.json` in `CODEX_HOME` | `auth.json` | `auth.json` |
| Z.AI | `ZAI_CODING_API_KEY[_SUFFIX]` from the environment or the env file | same | same (the env file is read as `KEY=value` lines) |

A login kept in an OS credential store that the kit cannot read (a Codex
keyring, Windows Credential Manager) is reported
as `no_login` with that cause, never guessed. The bar uses block characters on
a UTF-8 console and `#`/`-` otherwise; colour needs a terminal (on Windows one
that announces itself) and is never written into pipes or `--json`.

## Safety, in short

The token lives in memory and in one request header. Requests go to the fixed
`https` hosts above (a loopback override exists for tests and refuses any other
host), no redirect is followed, bodies are capped at 1 MiB. See
[SECURITY](SECURITY.md#quota-queries-ak-usage). The Grok CLI offers only
per-session usage and xAI's balance needs a separate management key, so both
stay `n/d` rather than asking for a second credential.

## Not in this version

A watch mode, token totals from local transcripts, Cursor (browser cookies are
never read), Azure quota, account identity, a cache, alert thresholds,
Windows Credential Manager and the China host of
Z.AI. Adding a source: a parser in `lib/usage.py`, its table in
`providers.toml` ([kinds](kinds.md#usage-sources)), a fixture and a test.
