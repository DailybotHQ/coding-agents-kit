# Orchestration patterns and the selection policy

Read this when you plan a batch for several accounts, when `ak pick` gives an
answer you need to explain, or when a lane fails.

## The selection policy (what `ak pick` computes)

`ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT] [--count N] [--exclude @profile]... [--allow-unknown] [--json] [--timeout SECONDS]`
reads the same rows as `ak usage` and never changes anything.

1. Only `ok` accounts are eligible. `expired`, `no_login`, `no_scope`,
   `rate_limited` and `error` are listed with the reason. Accounts with no
   readable quota (`unsupported`, e.g. Cursor) are left out unless
   `--allow-unknown`, which admits the connected ones last, with unknown
   headroom.
2. The windows that apply: every window without a model scope (`5h`, `7d`,
   a provider's windows) plus the model-only ones (`7d-<model>`) that match
   `--model`. Without `--model`, a model-only weekly window does not count —
   a Team seat has no global weekly cap.
3. A window whose reset time has passed counts as unused.
4. Windows of 7 days or more keep `--reserve` percent (default 10) unused;
   the 5-hour window has no reserve.
5. Headroom = the smallest free share among those windows; that window is
   the `binding_window`. `--need WIN:PCT` requires the window whose id is
   exactly `WIN` to keep `PCT` percent free.
6. Ranking: headroom, then the account whose weekly window resets first
   ("spend what expires first"), then the order of `ak usage`.

## Worked examples

Accounts (generic names): Claude `@default` (Max) 5-hour 10%, 7-day all
models 80%; `@tribu` (Team) 5-hour 0%, 7-day all models 24%, 7-day Fable
11%; `@work1`, `@work2`, `@work3` (Team) only 5-hour and 7-day Fable windows,
all at or near 0% with different reset times (Fable resets: `@work1` in
1h 28m, `@work2` in 18h, `@work3` in 2d 13h). Codex: four accounts at 0%;
`@work1`'s weekly window resets first. Z.AI `@default`: 5-hour 36%,
7-day 60%.

| Command | Answer | Why |
| --- | --- | --- |
| `ak pick claude` | `@work2` (100%) | Team seats have no weekly cap that applies; `@default` has only 10% (90 − 80) |
| `ak pick claude --model fable` | `@work1` | the Fable window now counts (90% with the reserve) for all three seats; `@work1`'s resets first |
| `ak pick claude --count 3` | `@work2`, `@work3`, `@work1` | 100, 100, 90 |
| `ak pick claude --need 7d:30` | `@tribu` | only `@default` and `@tribu` have a `7d` window; `@default` has 10% free |
| `ak pick claude-glm` | Z.AI `@default` (30%) | 7-day: 90 − 60 |
| `ak pick codex` | `@work1` | equal headroom; its weekly window resets first; resets available never count |
| `ak pick cursor` | exit 1 | no readable quota; `--allow-unknown` admits it with unknown headroom |

## Fan-out

```bash
ak pick claude --count 2 --json
git worktree add ../wt-parser -b lane/parser
git worktree add ../wt-docs -b lane/docs
ak run claude @work2 --cwd ../wt-parser --timeout 1800 --output-format json -- "Refactor the parser in this worktree; keep its tests green; commit." > parser.json &
ak run claude @work3 --cwd ../wt-docs --timeout 1800 --output-format json -- "Update the docs for the parser change in this worktree; commit." > docs.json &
wait
```

Then, per lane: read the JSON, run the repository's gate in the worktree,
merge the lane branch only if it passes, `git worktree remove` the worktree.

## Second opinion

The writer and the reviewer use different vendors (different blind spots).
The reviewer gets a read-only prompt and the writer's worktree:

```bash
ak pick codex --need 5h:20
ak run codex @work1 --cwd ../wt-parser --output-format json -- "Review the diff of this worktree against main for correctness and missing tests; list findings with file and line; change nothing."
```

Treat the findings as claims: confirm each one before acting on it.

## Pipeline

Plan → implement → review, each step on its own account and vendor:

```bash
ak run codex @work1 --output-format json -- "Write an implementation plan for the task in PLAN.md; do not edit code."
ak run claude @work2 --cwd ../wt-impl --output-format json -- "Implement PLAN.md in this worktree; run the tests; commit."
ak run codex @work3 --cwd ../wt-impl --output-format json -- "Review this worktree against PLAN.md; findings only."
```

## Failover in practice

1. A lane returns exit 3, a limit message, or exit 4.
2. Remove its worktree and branch (`git -C ../wt-parser reset --hard`,
   `git worktree remove ../wt-parser`, `git branch -D lane/parser`) — only
   the ones you created.
3. Re-pick without that account: `ak pick claude --exclude @work2`.
4. Recreate the worktree and run once more. A second failure stops the lane;
   tell the user what happened and which account needs attention.

## Spend report

After the batch, one `ak usage --json`. Report per account used: the binding
window before and after, and when it resets. Do not query again until the
next batch.
