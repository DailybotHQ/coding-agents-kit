# Permissions posture

**Autonomy by default.** `ak <kind>` adds the CLI's own autonomy flag, so the
agent edits files and runs commands without asking. Autonomy is meant for
disposable or sandboxed environments (containers, virtual machines,
throwaway worktrees). On a host you care about, opt out: the opt-out always
wins.

| How | Scope |
| --- | --- |
| nothing (the default) | every launch adds the CLI's autonomy flag |
| `ak <kind> --ask …` | this launch (or this `ak run`) asks: the CLI's own ask flag instead of its autonomy flag |
| `AGENTKIT_PERMISSIONS=ask` in the environment or in `~/.config/agentkit/env` | every launch that sees it asks, nested launches included |
| `ak <kind> --auto …` / `AGENTKIT_PERMISSIONS=auto` | explicit autonomy (the default made explicit) |

Resolution: **the opt-out always wins.** `--ask`, or `AGENTKIT_PERMISSIONS=ask`
(set by you or inherited from an `ak` that asked), means no autonomy flag — even when
the command also says `--auto`, so an agent cannot type its way out of your
opt-out. Otherwise the launch is autonomous (`--auto`,
`AGENTKIT_PERMISSIONS=auto`, or the default). An inherited
`AGENTKIT_PERMISSIONS=ask` also outranks `AGENTKIT_PERMISSIONS=auto` in your
env file. `--ask` with `--auto` on one command is a usage error (exit 2).
Any other value of `AGENTKIT_PERMISSIONS` is a usage error and launches
nothing.

## What the default adds — the CLI's own flag, nothing else

| Kind | Flag added | What the CLI documents |
| --- | --- | --- |
| `claude`, `claude-glm` | `--dangerously-skip-permissions` | bypass all permission checks |
| `codex`, `codex-*` | `--dangerously-bypass-approvals-and-sandbox` | no approvals and no sandbox |
| `cursor` | `--force` | allow commands unless explicitly denied |
| `opencode`, `opencode-*` | `--auto` | auto-approve permissions that are not explicitly denied |
| `pi`, `pi-*` | `--approve` | trust project-local files for this run (Pi has no per-tool approval prompt) |
| `cline`, `cline-*` | `--yolo` | auto-approve a limited tool set for unsupervised runs |
| `grok` | `--always-approve` | approve every tool call |
| `antigravity` | `--dangerously-skip-permissions` | auto-approve every tool permission request |

The flags live only in `providers.toml` (`auto = […]`); no code path spells
one. For all 20 kinds, the `permissions` test scope proves that a default
launch carries exactly its own flag and that `--ask` or
`AGENTKIT_PERMISSIONS=ask` removes it. Listing modes (`ak cursor -l`,
`ak cline -r`) never carry one.

`--ask` and `--auto` may sit anywhere before the first CLI argument
(`ak claude --ask @work -c` and `ak claude @work -c --ask` are the same);
after `--` or after a CLI argument they belong to the CLI.

## What the opt-out adds — ask is forced, not assumed

An account's own settings can default to an autonomous mode (Claude's
`permissions.defaultMode`, Codex's `approval_policy`), so leaving the
autonomy flag out is not enough. Under the opt-out, `ak` passes each CLI's
explicit ask flag where the CLI has one:

| Kind | Flag added under the opt-out | `ak run` (headless) |
| --- | --- | --- |
| `claude`, `claude-glm` | `--permission-mode default` | the same |
| `codex`, `codex-*` | `--ask-for-approval on-request --sandbox workspace-write` (a stricter `--sandbox` / `-s` you pass replaces the pinned one) | `--sandbox workspace-write` (`codex exec` takes no approval flag) |
| `grok` | `--permission-mode default` | the same |
| `cursor`, `opencode`, `pi`, `cline` (and their provider kinds), `antigravity` | nothing: the CLI has no ask flag, and leaving its autonomy flag out is its ask mode | nothing |

Codex's pinned `--sandbox workspace-write` also applies to an account whose
own config is stricter (`sandbox_mode = "read-only"`): pass `-s read-only`
after `--` to keep it — a stricter sandbox replaces the pinned one.

**A user mode flag cannot undo the opt-out.** Under the opt-out, `ak` owns
the CLI's permission flags: an argument after `--` (or after the first CLI
argument) that would **loosen** the CLI's permission or approval mode is a
usage error (exit 2) and launches nothing — its autonomy flag, Codex's
`-a` / `--ask-for-approval` / `--approve-for-me` / `--full-auto`, a Codex
config override of `approval_policy`, `sandbox_mode`, `sandbox_workspace_write`
or `sandbox_permissions` (`-c` / `--config`, also
profile-scoped keys such as `profiles.x.sandbox_mode`),
Cursor's `--force` / `-f` / `--yolo` / `--auto-review`, and any mode value
outside the allowed ones. Options are read the way the CLIs parse them:
`--opt value`, `--opt=value`, `-o value`, `-ovalue`, `-o=value`, short
clusters (`-fw`) for CLIs that accept them, and Antigravity's Go-style
`-opt`. Stricter or equal modes stay allowed:

| CLI | Allowed under the opt-out |
| --- | --- |
| claude | `--permission-mode default`, `manual`, `plan` or `dontAsk` |
| grok | `--permission-mode default`, `plan` or `dontAsk` |
| codex | `--sandbox` / `-s` `read-only` or `workspace-write` |
| antigravity | `--mode plan` |

Plain words (a prompt) are never matched, and a bare `--` ends the options —
except right after an option that may be waiting for its value, where the CLI
would read `--` as that value (so `--verbose -- <flag>` is checked too; put
the prompt first if it must contain such a word).
Without the opt-out every argument passes through to the CLI untouched. The
data lives in `providers.toml` (`ask`, `run.ask`, `ask_conflicts`,
`ask_values`, `ask_config`, `ask_clusters`, `ask_value_opts`, `ask_yield`,
`ask_single_dash_long`); the
`permissions` test scope proves the flag, every refusal and every allowed
case for each CLI.

`ak pick --kinds … --json` under the opt-out reports `launch.permissions:
"ask"` **and** puts `--ask` in `launch.argv`, so the suggested command asks
even where `AGENTKIT_PERMISSIONS` is not inherited.

## The opt-out is inherited, autonomy is not exported

When a launch asks, `ak` passes `AGENTKIT_PERMISSIONS=ask` to the CLI it
starts, so an agent that launches another agent (`ak run codex …` from inside
a Claude session) asks too — even if your env file says
`AGENTKIT_PERMISSIONS=auto` (the nested `ak` re-reads it, and the inherited
opt-out outranks it). When a launch is autonomous, `ak` removes
`AGENTKIT_PERMISSIONS` from the CLI's environment, and nested launches follow
the default.

## Trusting the launch folder: `--trust-cwd`

A new account opened in a new folder stops at its CLI's folder-trust screen
(Claude: "Do you trust the files in this folder?", Codex: "Trust this
folder?", Grok: "Do you trust the contents of this directory?"). `--trust-cwd` on `ak <kind>` or `ak run`, or
`AGENTKIT_TRUST_CWD=1` in the environment (inherited by nested `ak`), marks
the launch folder (`--cwd` for `ak run`) as trusted in that profile's own
config before the CLI starts:

| CLI | File | Change |
| --- | --- | --- |
| Claude Code | `.claude.json` at the account root (the profile directory; `CLAUDE_CONFIG_DIR` or `~` for `@default`) | `projects["<folder>"].hasTrustDialogAccepted = true`, every other key kept |
| Codex | `config.toml` in the profile (`CODEX_HOME`) | `[projects."<folder>"]` `trust_level = "trusted"`, appended only when that table is absent |
| Grok | `trusted_folders.toml` in the profile (`GROK_HOME`, `~/.grok` for `@default`) | `[folders."<repository root>"]` `trusted = true`, `decided_at = <epoch seconds>`, appended only when that table is absent (since 0.6.1) |

Grok asks about the **repository**, not the folder it starts in: the main
working tree of the git repository around the folder — from a linked
worktree (`git worktree add`), the repository the worktree belongs to — and
the folder itself outside a repository. A trusted parent folder does not
count. `ak` finds that root from the files git writes (`.git`, a worktree's
`commondir`; no `git` executable needed); a worktree link it cannot read
leaves the worktree itself, never a guessed parent.

Opt-in only: no flag, no write. Idempotent; one stderr line names the file
it changed. Other CLIs: a note and no write. It answers no other screen and
does not change the permission posture: trusting a folder is not autonomy.
Claude's bypass-permissions acknowledgement is a one-time step you take per
profile, when you create it (open `ak claude @name` once and accept); no
agent ever answers it.

A symlinked config (a dotfiles repository) is updated where it points, and a
link that leaves the profile is refused. On Windows the entry is written with
the folder's native path; whether each CLI looks it up in that form there is
not verified yet.

## The `classic` aliases

`ak alias preset classic --on` recreates `claudex`, `codexx`, `cursorx`,
`opencodex`, `pix`, `clinex`, `grokx` and `agyx` as plain shortcuts for
`ak <kind>`, for people migrating from the old wrappers. They follow your
posture: the default, or the opt-out. It ships **off**. The `providers`
preset (`ak alias preset providers --on`) does the same for the provider
kinds, under their own names (`codex-glm`, `claude-glm`, …). Custom aliases may
carry `--ask` or `--auto` (`ak alias add careful claude --ask`). See
[install](install.md).

## Hosts and containers

A disposable container whose only writable world is the repository is the
setting autonomy is designed for: the container is the sandbox. Codex's own
sandbox (bubblewrap) cannot create user namespaces inside most containers,
which is why Codex needs `--dangerously-bypass-approvals-and-sandbox` there
at all. On a host, set `AGENTKIT_PERMISSIONS=ask` in `~/.config/agentkit/env`
unless you accept that agents act without asking.

`ak doctor` reports the effective posture (`permissions: auto|ask`) and warns
when autonomy is on outside a container.
