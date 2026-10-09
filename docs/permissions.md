# Permissions posture

**Pass-through by default.** `ak <kind>` adds no permission-bypass flag: the
CLI asks before it edits files or runs commands exactly as it does when you
type its own name. Autonomy is an explicit opt-in, per launch or per
environment.

| How | Scope |
| --- | --- |
| `ak <kind> --auto …` | this launch (or this `ak run`) only |
| `AGENTKIT_PERMISSIONS=auto` in the environment or in `~/.config/agentkit/env` | every launch that sees it |
| `AGENTKIT_PERMISSIONS=ask` (or unset) | the default: nothing added |

Any other value of `AGENTKIT_PERMISSIONS` is a usage error (exit 2) and
launches nothing — a typo never turns autonomy on.

## What `--auto` adds — the CLI's own flag, nothing else

| Kind | Flag added | What the CLI documents |
| --- | --- | --- |
| `claude`, `claude-glm` | `--dangerously-skip-permissions` | bypass all permission checks |
| `codex`, `codex-*` | `--dangerously-bypass-approvals-and-sandbox` | no approvals and no sandbox |
| `cursor` | `--force` | allow commands unless explicitly denied |
| `opencode`, `opencode-*` | `--auto` | auto-approve permissions that are not explicitly denied |
| `pi`, `pi-*` | `--approve` | trust project-local files for this run (Pi has no per-tool approval prompt) |
| `cline`, `cline-*` | `--yolo` | auto-approve a limited tool set for unsupervised runs |
| `grok` | `--always-approve` | approve every tool call |

The flags live only in `providers.toml` (`auto = […]`); no code path spells
one, and the `permissions` test scope proves for all 19 kinds that a default
launch carries none of them and an opted-in launch carries exactly its own.
Listing modes (`ak cursor -l`, `ak cline -r`) never carry one.

`--auto` may sit anywhere before the first CLI argument
(`ak claude --auto @work -c` and `ak claude @work -c --auto` are the same);
after `--` or after a CLI argument it belongs to the CLI.

## Autonomy is not inherited

`ak` removes `AGENTKIT_PERMISSIONS` from the environment of the CLI it
starts. An agent that launches another agent (`ak run codex …` from inside a
Claude session) gets the default posture again unless it passes `--auto`
itself or the user's own env file says `AGENTKIT_PERMISSIONS=auto`. A
one-off `AGENTKIT_PERMISSIONS=auto ak claude` therefore never makes the
sub-agents of that session autonomous behind your back.

## The `classic` aliases

`ak alias preset classic --on` recreates `claudex`, `codexx`, `cursorx`,
`opencodex`, `pix`, `clinex` and `grokx` as `ak <kind> --auto` for people
migrating from the old wrappers. It ships **off**. See [install](install.md).

## The sanctioned opt-in: a container as the sandbox

The one place autonomy is a reasonable default is a disposable container
whose only writable world is the repository: the container is the sandbox.
Set `AGENTKIT_PERMISSIONS=auto` in that container's env file (or its image),
never on your host. Note that Codex's own sandbox (bubblewrap) cannot create
user namespaces inside most containers, which is why Codex needs
`--dangerously-bypass-approvals-and-sandbox` there at all.

`ak doctor` reports the effective posture (`permissions: ask|auto`).
