# Skills and agents catalog

Everything under `.agents/` in this repository. Commands are listed in
[COMMANDS_REFERENCE.md](COMMANDS_REFERENCE.md).

## Skills

| Skill | Path | Purpose |
| --- | --- | --- |
| `deepworkplan` | `.agents/skills/deepworkplan/` | DeepWorkPlan: create, execute, refine, resume, status, verify and upgrade plans (vendored, pinned in `skills-lock.json`) |
| `ai-diff-reviewer` | `.agents/skills/ai-diff-reviewer/` | the local diff review run in every plan's Final Review (vendored, pinned in `skills-lock.json`; configured by `.review/extension.md`) |

The product's own skill, `skills/agentkit/SKILL.md`, ships with the kit
(`ak --skill`); it is product code, not part of this agent kit.

## Agents

| Agent | Path | Use it to |
| --- | --- | --- |
| `architect` | `.agents/agents/architect.md` | shape a design change (kinds model, profiles, interface 1) |
| `executor` | `.agents/agents/executor.md` | implement one scoped task with tests and docs |
| `qa` | `.agents/agents/qa.md` | design and write checks in the bash harness |
| `reviewer` | `.agents/agents/reviewer.md` | review a change before merge |
| `security-auditor` | `.agents/agents/security-auditor.md` | audit against the threat model and public hygiene |
