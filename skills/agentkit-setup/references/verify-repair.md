# Flow E — verify and repair

```bash
# test: verify
python3 coding-agents-kit/lib/ak.py setup verify
```

`ak setup verify` is read-only. It prints one line per check (`ok`, `warn` or `fail`), a `fix:` line with the exact command when one exists, and a verdict; exit 0 when nothing fails, 1 otherwise. Add the user's wishes as options so it judges against them:

| Option | Adds checks |
| --- | --- |
| `--cli claude,codex` | `cli.<name>.installed` (repair: `ak install <name>`) |
| `--profile claude=@work,@2` | `profile.<cli>.<name>.exists` (repair: `ak profiles add …`) and `.login` (the person logs in) |
| `--keys ZAI_CODING_API_KEY` | `keys.<NAME>.set` — set or unset, never the value |
| `--expect-posture ask` | `posture.matches` (repair: a line for the env file) |

The install checks are always on: `install.marker`, `install.version`, `path.ak`, `python.version`, `envfile.exists`, `envfile.mode`, and `aliases.rc` for an install made with `--no-rc`.

## How to repair

1. Show the failures in plain words.
2. For each `fix:`, ask (the matching `[GATE: …]`), run it, then verify again.
3. A check with no `fix:` needs the person: an old python, a missing key value, a login.
4. Never repair by deleting profiles or the env file; never hand-edit what a command can do.

Use `ak setup verify --json` (schema `setup-verify-v1`) when a program reads the result.
