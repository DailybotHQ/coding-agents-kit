# Kinds

A **kind** is what you type after `ak`: a canonical CLI (`claude`, `codex`,
`cursor`, `opencode`, `pi`, `cline`, `grok`) or a CLI routed to another API
provider (`claude-glm`, `codex-azure`, `opencode-xai`, …). Kinds are data in
[`providers.toml`](../providers.toml); `lib/kinds.py` loads, validates and
resolves them. No CLI is named in the dispatcher's code.

| Kind | Executable | Provider variants | Profile home variable |
|---|---|---|---|
| `claude` | `claude` | `claude-glm` | `CLAUDE_CONFIG_DIR` |
| `codex` | `codex` | `codex-glm`, `codex-azure`, `codex-xai` | `CODEX_HOME` |
| `cursor` | `agent` (Cursor CLI) | — | `HOME` (profile home) + `AGENT_CLI_CREDENTIAL_STORE=file` |
| `opencode` | `opencode` | `opencode-glm`, `opencode-azure`, `opencode-xai` | `XDG_{CONFIG,DATA,STATE,CACHE}_HOME` |
| `pi` | `pi` | `pi-glm`, `pi-azure`, `pi-xai` | `PI_CODING_AGENT_DIR` |
| `cline` | `cline` | `cline-azure`, `cline-xai` | `CLINE_DIR` |
| `grok` | `grok` | (native xAI) | `GROK_HOME` |

Kind names equal Herdr's `--kind` values, so a kind is also what you pass to
`herdr agent start --kind`.

## Providers and their variables

Put these in `~/.config/agentkit/env` (mode 600). A named profile reads
`<KEY>_<SUFFIX>` instead of `<KEY>` (see [profiles](profiles.md)).

| Provider | Key | Optional settings (defaults) |
|---|---|---|
| Z.AI GLM (`*-glm`) | `ZAI_CODING_API_KEY` | `ZAI_DEFAULT_SONNET_MODEL` (`glm-5.3`), `ZAI_DEFAULT_OPUS_MODEL` (`glm-5.3`), `ZAI_DEFAULT_HAIKU_MODEL` (`glm-5.3-flash`), `ZAI_ANTHROPIC_BASE_URL`, `ZAI_CODING_BASE_URL`, `ZAI_CODEX_BASE_URL`, `ZAI_CODEX_DEFAULT_MODEL`, `ZAI_OPENCODE_DEFAULT_MODEL`, `ZAI_PI_DEFAULT_MODEL`, `ZAI_CODING_API_TIMEOUT_MS`, `ZAI_CODING_AUTO_COMPACT_WINDOW` |
| Azure OpenAI / Foundry (`*-azure`) | `AZURE_OPENAI_API_KEY` | **required:** `AZURE_OPENAI_RESOURCE` or `AZURE_OPENAI_BASE_URL`, and `AZURE_OPENAI_MODEL_DAILY` (your deployment name — there is no default to guess); optional `AZURE_OPENAI_MODEL_REASONING`, `AZURE_OPENAI_DEFAULT_MODEL` |
| xAI (`*-xai`, `grok`) | `XAI_API_KEY` | `XAI_BASE_URL` (`https://api.x.ai/v1`), `XAI_MODEL_DAILY` (`grok-4.3`), `XAI_MODEL_REASONING` (`grok-4.6`), `XAI_DEFAULT_MODEL` |

`grok` treats the key as optional: without one it uses the CLI's own
`grok login`.

## How a provider reaches the CLI — never as a file value

| CLI | Mechanism | What is written |
|---|---|---|
| Claude Code | environment (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, model variables) | nothing |
| Codex | overlay `<home>/<provider>.config.toml` + `codex -p <provider>` | `env_key = "<KEY>"` |
| OpenCode | one provider merged into `opencode.json` + `-m <provider>/<model>` | `"apiKey": "{env:<KEY>}"` |
| Pi | one provider upserted into `models.json` + `--provider/--model/--models` | `"apiKey": "$<KEY>"` |
| Cline | `cline auth …` then `cline -P openai -m <model> -k <key>` | Cline stores the key itself |

**Cline is the one documented exception**: it only accepts the key on its
command line (`-k`), and `cline auth` saves it in Cline's own settings inside
the profile. On a shared machine the key is visible in the process list while
Cline starts. Every other CLI reads the key from its environment.

Writers are merge-safe: they replace only their own provider entry, keep
everything else, refuse a file that does not parse (left byte-identical),
keep a one-time `<file>.agentkit.bak`, and write atomically with mode 600. A
Codex overlay without the kit's generated header is yours, and is refused
rather than overwritten.

## Adding a kind

1. Add `[kinds.<cli>-<provider>]` (and, for a new API, `[providers.<id>]`)
   to `providers.toml`. A new CLI needs a `[clis.<cli>]` block: executable,
   isolation, roots, session mapping, autonomy flag, headless mapping, login
   probe, install channel and, when Herdr integrates it, hook files.
2. Run `python3 lib/kinds.py check` — validation names every rule a broken
   entry violates (unknown CLI or provider, `{key}` outside a kind's env /
   Cline argv, an unpinned installer without a reason, …).
3. Add the kind to the contract table in `tests/py/kinds_checks.py` and run
   `bash tests/run.sh kinds dispatch`.

## Template language

`{NAME}` reads the environment (upper case); `{name}` reads a variable —
provider and kind variables, `root.<name>`, `dir`, `id`, `prompt`, `cwd`,
`seconds`, `kind`, `profile`. `{X:-default}` falls back when `X` is unset or
empty, and defaults nest. A leading `~` is the user's home. In an argv list,
an element that is exactly `{provider}`, `{session}`, `{auto}`, `{json}` or
`{timeout}` expands to a list. `{key}` is the profile's provider key: it is
resolved only into the CLI's environment (or Cline's argv) and never for
anything the kit prints.
