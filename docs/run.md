# `ak run` — one prompt, headless

```
ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] [--output-format text|json] [--ask | --auto] -- "<prompt>"
```

Runs one prompt non-interactively in `--cwd` (default: the current
directory) and exits. It is the headless half of interface 1: scripts, CI
and orchestrators (the DeepWorkPlan `agentkit` addon delegates through it)
can start any agent the same way and read one result.

- Words after `--` are joined with spaces into one prompt; `-- -` reads the
  prompt from stdin.
- `@profile` (or `AGENTKIT_PROFILE`) must already exist: `ak run` never asks
  questions and never creates a profile.
- Like every launch, a run adds the CLI's autonomy flag by default.
  `--ask` (or `AGENTKIT_PERMISSIONS=ask`) opts out for this run: the CLI runs
  in its own default posture, which for most headless CLIs means tools that
  need approval are refused rather than run. `--ask` with `--auto` is a usage
  error.
- `--timeout SECONDS` kills the whole process tree when it expires (`0` =
  none). Cline also receives it as its own `-t`.

**Windows:** a program that calls `ak run` must start the python core
directly — `py -3 <install>\lib\ak.py run …` — not `ak.cmd`. A batch file
lets `cmd.exe` re-parse its arguments, so a prompt containing `"` and `&`
could run commands. (`ak.cmd` is for typing at a prompt.) The kit itself
starts npm-installed CLIs as `node <script>` and refuses cmd metacharacters
for any other batch target.

## Mapping (frozen, per CLI)

| Kind | Command |
| --- | --- |
| claude | `claude -p "<prompt>" [--output-format json]` |
| codex | `codex exec [--json] -C <cwd> "<prompt>"` |
| cursor | `agent -p "<prompt>" [--output-format json] --trust` |
| opencode | `opencode run [--format json] "<prompt>"` |
| pi | `pi -p "<prompt>" [--mode json]` |
| cline | `cline "<prompt>" [--json] -c <cwd> [-t <timeout>]` |
| grok | `grok -p "<prompt>" [--output-format json] --cwd <cwd>` |

The CLI's process always starts in `<cwd>`. Provider kinds add their own
arguments (`codex exec -p azure …`, `opencode run -m xai/… …`) and
environment exactly as an interactive launch does; Cline variants run
`cline auth …` first (its output goes to stderr). The mapping lives in
`providers.toml` (`[clis.<cli>.run]`).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | the agent finished and reported success |
| 1 | the agent finished and reported failure (non-zero CLI exit, or an error in its JSON output) |
| 2 | usage error (bad option, missing `--` or prompt, `--cwd` not a directory, unknown kind) |
| 3 | the CLI is not installed, or not logged in for that profile, or its provider key or the profile is missing |
| 4 | timeout: the process tree was killed |
| 5 | cancelled: `ak run` received SIGTERM (or SIGINT) and killed the process tree |
| ≥ 64 | kit internal error |

"Not logged in" is decided from credential files only when the CLI's login
lives in files (Claude, Codex, Grok; or an API-key variable those CLIs
honour); for the others the run starts and the CLI's own error, if any, is
exit 1.

## `--output-format json`

stdout is **exactly one JSON object**, also when the run never started; the
CLI's own output (its transcript, including its JSON stream) goes to stderr.

```json
{"interface": 1, "kind": "codex", "profile": "@default", "cwd": "/repo",
 "exit": 0, "duration_s": 41.207, "result_text": "Done: …", "cli_exit": 0, "truncated": false}
```

| Field | Meaning |
| --- | --- |
| `interface` | `1` |
| `kind`, `profile`, `cwd` | what ran, where (`profile` is `@default` or `@name`) |
| `exit` | the exit code above (same as the process's) |
| `duration_s` | wall-clock seconds |
| `result_text` | the agent's final answer, extracted from the CLI's JSON (Claude/Cursor/Grok `result`, Codex's last `agent_message`, OpenCode's last `text` part, Pi's last assistant message, Cline's `completion_result`); the raw output when the shape is not recognised |
| `cli_exit` | the CLI's own exit status (`null` when it never started; negative = killed by that signal) |
| `truncated` | `result_text` was cut at 64 KiB, or the CLI's output exceeded the 8 MiB kept for extraction |
| `error` | present only when the run never started: the one-line reason |

The result is the agent's claim. A caller that needs proof runs its own
checks afterwards (DeepWorkPlan treats a delegate's result as `asserted`
evidence until its own gate runner observes it).

## Examples

```bash
ak run claude -- "summarise the README in one line"
ak run codex @work --cwd ~/src/api --timeout 900 --output-format json -- "fix the failing test in tests/test_auth.py"
{ echo "Review this diff:"; git diff; } | ak run pi --output-format json -- -
```
