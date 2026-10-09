# .agents/

The cross-agent kit for working **on** this repository (not part of the
product). `.claude` and `.cursor` are symlinks to this directory.

- `agents/` — personas (reviewer, executor, architect, qa, security-auditor)
- `commands/` — thin `dwp-*`, `skill-create` and `agent-create` delegators
- `skills/` — vendored skills, pinned in `skills-lock.json`; never hand-edit them
- `docs/` — the catalog and the commands reference; keep them matching disk

Start with [AGENTS.md](../AGENTS.md).
