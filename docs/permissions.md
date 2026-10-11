# Permissions posture

**Autonomy by default.** `ak <kind>` adds the CLI's own autonomy flag, so the
agent edits files and runs commands without asking. Autonomy is meant for
disposable or sandboxed environments (containers, virtual machines,
throwaway worktrees). On a host you care about, opt out: the opt-out always
wins.

| How | Scope |
| --- | --- |
| nothing (the default) | every launch adds the CLI's autonomy flag |
| `ak <kind> --ask …` | this launch (or this `ak run`) asks: no flag added |
| `AGENTKIT_PERMISSIONS=ask` in the environment or in `~/.config/agentkit/env` | every launch that sees it asks, nested launches included |
| `ak <kind> --auto …` / `AGENTKIT_PERMISSIONS=auto` | explicit autonomy (the default made explicit) |

Resolution: **the opt-out always wins.** `--ask`, or `AGENTKIT_PERMISSIONS=ask`
(set by you or inherited from an `ak` that asked), means no flag — even when
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
folder?"). `--trust-cwd` on `ak <kind>` or `ak run`, or
`AGENTKIT_TRUST_CWD=1` in the environment (inherited by nested `ak`), marks
the launch folder (`--cwd` for `ak run`) as trusted in that profile's own
config before the CLI starts:

| CLI | File | Change |
| --- | --- | --- |
| Claude Code | `.claude.json` at the account root (the profile directory; `CLAUDE_CONFIG_DIR` or `~` for `@default`) | `projects["<folder>"].hasTrustDialogAccepted = true`, every other key kept |
| Codex | `config.toml` in the profile (`CODEX_HOME`) | `[projects."<folder>"]` `trust_level = "trusted"`, appended only when that table is absent |

Opt-in only: no flag, no write. Idempotent; one stderr line names the file
it changed. Other CLIs: a note and no write. It answers no other screen and
does not change the permission posture: trusting a folder is not autonomy.
Claude's one-time bypass-permissions warning stays the user's to accept.

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
