# `ak doctor` and `ak env`

Both are read-only, print no secret value, and are part of **interface 1**:
other tools (herdr-peers, devcontainer-kit, the DeepWorkPlan pack) check
`ak doctor --json` → `"interface": 1` before relying on anything else.

## `ak doctor [--json]`

The text form is for people: kit version and root, the env file and its
mode, the permission posture, every CLI (version, login state, path or the
`ak install` command), provider kinds (ready / key unset), key **names**,
profiles, aliases, Herdr hooks and problems to fix. Inside a container it
says so first: it reports the container, not your host.

The JSON form is the contract. Schema: [`schema/doctor-v1.json`](schema/doctor-v1.json).

```json
{
  "interface": 1,
  "version": "0.1.1",
  "os": "macos",
  "kinds": {
    "claude":     { "cli": "claude", "provider": null,  "installed": true, "path": "/…/claude", "version": "2.1.295 (Claude Code)", "logged_in": true },
    "claude-glm": { "cli": "claude", "provider": "zai", "installed": true, "path": "/…/claude", "version": "2.1.295 (Claude Code)", "logged_in": false },
    "…": {}
  },
  "profiles": { "claude": ["work"], "codex": [], "…": [] },
  "keys": ["XAI_API_KEY", "ZAI_CODING_API_KEY_WORK"],
  "permissions": "ask",
  "aliases": { "classic": false, "custom": [] },
  "herdr_hooks": { "claude": { "@default": "present", "@work": "absent" }, "…": {} },
  "env_file": { "path": "/…/.config/agentkit/env", "exists": true, "mode": "600" },
  "problems": []
}
```

| Key | Meaning |
| --- | --- |
| `interface` | always `1` in v0.x; a breaking change bumps it (and the major version) |
| `kinds.<kind>.installed` / `path` / `version` | the CLI on `PATH` (Cursor: the real Cursor binary, never Grok's `agent`); version from `<cli> --version` (5 s timeout) |
| `kinds.<kind>.logged_in` | `@default` only. Canonical kinds: `true`/`false` from credential **file presence** (and credential variable names), `null` when files cannot tell (Cursor's default Keychain login, OpenCode/Pi/Cline env-based providers). Provider kinds: whether their key variable is set |
| `profiles` | named profiles per CLI (`@default` is implicit) |
| `keys` | names of provider key variables that are set (base and per profile) — never values |
| `permissions` | `ask` (pass-through) or `auto`; an invalid `AGENTKIT_PERMISSIONS` reports `ask` plus a problem (launches refuse) |
| `aliases` | the `classic` preset on/off and custom alias names |
| `herdr_hooks` | per Herdr-integrated CLI, per profile: whether Herdr's state hook files are present in that home |
| `env_file`, `problems` | where the env file is, its mode, and anything to fix |

Consumers must ignore keys they do not know: minor versions may add some.
No credential file is opened, with one exception: Claude's `.claude.json`
is checked for the `oauthAccount` entry that names the account (it holds no
token; the token is in the Keychain on macOS).

## `ak env <kind> [@profile]`

Prints the environment that points a CLI at a profile, as `KEY=VALUE`
lines — no `export`, no quoting, never a secret value. Exit 0 with no output
means "the CLI's own home" (`@default` of a canonical kind). A missing
profile exits 3; `AGENTKIT_PROFILE` is honoured when no `@profile` is given.

```console
$ ak env claude @work
CLAUDE_CONFIG_DIR=/home/me/.local/share/agentkit/profiles/claude/work
$ ak env cursor @2
AGENT_CLI_CREDENTIAL_STORE=file
CURSOR_CONFIG_DIR=/home/me/.local/share/agentkit/profiles/cursor/2/home/.cursor
HOME=/home/me/.local/share/agentkit/profiles/cursor/2/home
```

Its purpose is letting another launcher start the raw CLI in a profile —
Herdr in particular:

```bash
args=(); while IFS= read -r kv; do args+=(--env "$kv"); done < <(ak env claude @work)
herdr pane split --current --direction right "${args[@]}"
herdr agent start reviewer --kind claude --pane <new-pane-id>
```

**Provider kinds** print their non-secret settings too (base URL, models),
but an environment cannot carry everything they need: the key itself is
never printed, and Codex/OpenCode/Pi/Cline variants also need command-line
arguments or a config file that `ak` writes at launch. `ak env` names what is
missing on stderr; for those kinds run the kind itself in the pane instead:
`herdr pane run <id> "ak claude-glm @work"`. When a profile deliberately has
no key of its own (`grok @2` without `XAI_API_KEY_2`), `ak env` prints the
key variable **empty** so the pane cannot inherit profile 1's key.
