# Commands reference

Invoke a command as `/<name>` in Claude Code, as `#<name>` in agents that
intercept slash syntax, or in plain text ("run `<name>`") on hosts without
slash commands. Each one is a thin delegator: the flow lives in the
vendored `deepworkplan` skill.

| Command | File | Routes to |
| --- | --- | --- |
| `dwp-create` | `.agents/commands/dwp-create.md` | `deepworkplan/create` |
| `dwp-execute` | `.agents/commands/dwp-execute.md` | `deepworkplan/execute` |
| `dwp-refine` | `.agents/commands/dwp-refine.md` | `deepworkplan/refine` |
| `dwp-resume` | `.agents/commands/dwp-resume.md` | `deepworkplan/resume` |
| `dwp-status` | `.agents/commands/dwp-status.md` | `deepworkplan/status` |
| `dwp-verify` | `.agents/commands/dwp-verify.md` | `deepworkplan/verify` |
| `dwp-upgrade` | `.agents/commands/dwp-upgrade.md` | `deepworkplan/upgrade` |
| `skill-create` | `.agents/commands/skill-create.md` | `deepworkplan/author` (create a skill) |
| `agent-create` | `.agents/commands/agent-create.md` | `deepworkplan/author` (create an agent) |
