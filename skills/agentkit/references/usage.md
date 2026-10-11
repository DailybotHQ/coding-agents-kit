# Usage: which account has room

Read this when the user asks how much quota is left, which account to use,
or what a row of `ak usage` means, or before you start a long task or
several delegates. For adding accounts and logging in, read
[accounts.md](accounts.md).

`ak usage` and `ak pick` are **read-only**: they never refresh a login,
never spend a reset, never print a token and never write under a profile.
But they ask each vendor with the user's own logins, so run them once per
batch of work and when the user asks, never in a loop.

## Reading the table

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

One block per CLI or provider, its title line first (`claude · Claude
Code`). A tip that applies to the whole block sits on the title line.

| Column | What it says |
| --- | --- |
| PROFILE | the account: `@default` is the CLI's own home, `@name` a profile. Shown once; the lines under it belong to the same account |
| PLAN | the vendor's own plan label (`max`, `team`, `plus`, `pro`); `-` when not reported |
| WINDOW | one of the vendor's own limits. `5-hour` is the short rolling window; `7-day all models` the weekly cap; `7-day Fable only` a weekly cap that counts one model only; `resets` is not a window (see below) |
| USED | percent of that window already used, as a bar and a number. Room left is 100 minus it |
| RESET | when that window starts over. After the last column, Z.AI shows credits used out of the limit |

Reading the example:

- `claude @default` has room now (5-hour 10%) but its week is nearly spent
  (80%): fine for a short task, a poor choice for a long one.
- `claude @team` is the roomiest account with a weekly cap (24%).
- `claude @work1` is on Team without a global weekly cap: it shows only the
  5-hour window and a Fable-only weekly window. Work that does not use that
  model is bounded by the 5-hour window alone.
- `codex @default` is unused, and holds 3 resets.
- `zai @default` has 64% of its 5-hour window but only 40% of its week left:
  the week binds.
- `cursor` and `xai` are **connected** (a login found, a key set) but have
  no quota the kit can read: they work, with unknown headroom.

Accounts with no readable quota and no connection fold into a closing `n/d`
line. `ak usage -v` lists every row with its full reason.

```bash
ak usage                       # the table
ak usage claude                # one CLI (or a kind: claude-glm selects the Z.AI rows)
ak usage codex @work1 --json   # one account, as usage-v1
```

## usage-v1 fields

`ak usage --json` is one object: `schema` (`usage-v1`), `interface` (1),
`generated_at`, `rows[]`. Check `schema` before reading anything else.

| Row field | Meaning |
| --- | --- |
| `cli`, `profile` | the account (`zai` for the Z.AI provider rows) |
| `kinds` | every kind that shares this credential (`claude-glm`, `codex-glm`, …) |
| `plan` | the vendor's plan label, or `null` |
| `status` | see the table below |
| `windows[]` | `id` (`5h`, `7d`, `7d-<model>`), `label`, `used_pct` (0-100 or `null`), `resets_at` (UTC), `window_seconds`; optional `used`, `limit`, `unit` (Z.AI credits). Empty unless `ok` |
| `source` | the adapter, or `none` |
| `error` | one line for every status except `ok` and `unsupported` |
| `reason` | why an `unsupported` row has no quota |
| `connected` | optional, `unsupported` rows: a login found or a key set |
| `resets_available` | optional: Codex resets the account holds |

No row ever carries an account identity (e-mail, organisation, id) or a
secret.

## Status → action

| Status | Means | What you do |
| --- | --- | --- |
| `ok` | the windows are current | use the numbers |
| `expired` | the login passed its own expiry | tell the user to open that profile once (`ak claude @work`); its CLI renews the login. Do not renew it yourself |
| `no_login` | no readable login for that profile | tell the user to log in as that profile ([accounts.md](accounts.md)); pick another account meanwhile |
| `no_scope` | the login lacks the permission or was rejected | tell the user to sign in again with a full login |
| `rate_limited` | the usage endpoint answered 429 | do not retry now; ask again later, once |
| `unsupported` | no readable quota (`n/d`); `connected` says whether it works anyway | usable with unknown headroom; `ak pick --allow-unknown` admits it last |
| `error` | network, timeout, HTTP or unexpected-shape failure | report the one-line error; the other rows still count |

Exit: 0 every row `ok` or `unsupported`; 1 a row needs attention; 2 usage
error; 3 nothing matches the filter.

## Plan-specific windows

- **Team without a global weekly cap** (Claude Code): only `5h` and
  `7d-<model>` windows. Without a model in play, the 5-hour window is the
  only limit.
- **Model-only windows** (`7d-fable`, labelled `7-day Fable only`): they
  limit work that uses that model only. They govern a choice only when you
  will use that model (`ak pick … --model fable`).
- **Z.AI credits:** `5-hour` and `7-day` windows with `used`/`limit` in
  credits (`4.36K/12K`). One key is one row shared by every `*-glm` kind of
  that profile.
- **Codex resets:** `resets  3 available` is the number of limit resets the
  account holds. Only the user spends one, with `/usage` inside Codex. A
  reset is never headroom: the kit never spends one and neither do you.

## Choosing an account: `ak pick`

```
ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT]
        [--count N] [--exclude @profile]... [--allow-unknown] [--json] [--timeout SECONDS]
```

`ak pick` reads the same rows as `ak usage` (read-only, same vendor
requests) and returns the account with the most usable room for a kind:

1. Only `ok` rows are eligible; `unsupported` ones join last with
   `--allow-unknown`. Every other status is excluded with that reason.
2. Windows without a model scope govern; a `7d-<model>` window governs only
   when `--model` matches it.
3. A window whose reset already passed counts as unused.
4. Windows of 7 days or more keep `--reserve` percent unused (default 10,
   0-50); the 5-hour window keeps none.
5. Headroom is the smallest free percent over the governing windows; that
   window is the binding one. `--need WIN:PCT` requires at least `PCT` free
   in the window `WIN` (`5h`, `7d`, `7d-<model>`); an account without that
   window does not qualify.
6. Ranking: headroom, then the account whose long window resets first
   (capacity that resets soon is lost if unused), then kit order with
   `@default` first.

`--count N` (1-16) returns the top N distinct accounts for parallel work;
`--exclude @name` skips accounts already busy. Text output is one line per
account:

```text
claude @work2  headroom 100%  binding 5h  resets in 3h 48m
```

| Exit | Meaning |
| --- | --- |
| 0 | at least one account chosen |
| 1 | none qualifies; stderr names the soonest reset among measured accounts |
| 2 | usage error |
| 3 | nothing matches the filter |
| ≥ 64 | kit internal error |

`--json` is schema `pick-v1`: `chosen[]` and every evaluated row in
`candidates[]` (`status`, `eligible`, `headroom_pct`, `binding_window`,
`resets_at`, `excluded_reason`), plus `soonest_reset`.

### Worked examples (reserve 10%)

The full table behind these examples has two more Claude Team accounts,
`@work2` and `@work3` (5-hour 0%, 7-day Fable only 0%, resetting in 18h 28m
and 2d 13h), and four Codex accounts, all at 0%, whose 7-day windows reset in
6d 20h (`@work1`), 6d 23h (`@default`, `@work2`) and 7d 0h (`@work3`).

| # | Command | Result | Why |
| --- | --- | --- | --- |
| E1 | `ak pick claude` | `@work2`, headroom 100 | default 10 (90−80), team 66 (90−24), work1 90, work2 and work3 100 (no weekly cap governs); tie → profile order |
| E2 | `ak pick claude --model fable` | `@work1` | the Fable window now governs with its reserve: work1, work2, work3 all 90; tie → work1's Fable window resets first |
| E3 | `ak pick claude --count 3` | `@work2`, `@work3`, `@work1` | 100, 100, 90; team (66) and default (10) rank after |
| E4 | `ak pick claude --need 7d:30` | `@team` | only default and team report `7d`: default has 10 free, team 66 |
| E5 | `ak pick claude-glm` | `zai @default`, headroom 30 | 5-hour 64 free, 7-day 90−60 = 30; binding `7d` |
| E6 | `ak pick codex` | `@work1` | all four at 90 (the 7-day reserve binds); tie → earliest 7-day reset; resets never count |
| E7 | `ak pick cursor` | exit 1, `no readable quota` | connected only; with `--allow-unknown` → `@default`, headroom unknown |
| E8 | `ak pick claude @default --need 5h:95` | exit 1 | 5-hour free 90 < 95; stderr names that account's soonest reset |

```bash
ak pick codex --json                         # one account, every candidate with its reason
ak pick claude --count 3 --exclude @work1    # three accounts for parallel work, one already busy
ak pick claude @work2 --need 5h:50           # a check: does this account have half its 5 hours?
```

On exit 1, tell the user when the soonest reset is and wait for them;
do not switch to an account they did not offer, and do not ask them to
spend a Codex reset unless they bring it up.

## When not to query

- Never in a loop, a `watch`, or after each delegate finishes: once before a
  batch, once after it for the spend report, and whenever the user asks.
- Not for a short task on the account the user already chose.
- Not to retry a `rate_limited` or `error` row right away.
- Not to compare accounts the user did not offer for this work.
- Never to renew a login, spend a reset, or create or remove a profile: none
  of those is a quota action, and each one is the user's.
