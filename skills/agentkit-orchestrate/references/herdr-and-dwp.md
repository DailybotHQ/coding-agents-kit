# Interactive lanes in Herdr panes, and Deep Work Plans (optional)

Read this only when the user works in Herdr or runs Deep Work Plans. Neither
is required: the loop in SKILL.md works with `ak` and git alone.

## Herdr: one pane per lane

A lane that needs interaction, runs long, or must be watched gets a Herdr
pane instead of a headless `ak run`. Herdr's own skill (`herdr --skill`) is
the authority for every `herdr` command; this page only names them.

1. Pick the account: `ak pick claude --count 2`.
2. Create the lane's worktree: `git worktree add ../wt-lane1 -b lane/lane1`.
3. Open a pane in that worktree and start the agent on the chosen account.
   Either run `ak claude @work2` in the pane (provider kinds need this form),
   or pass the profile's environment to the pane — `ak env` prints
   `KEY=VALUE` lines of names and paths, never secret values:

```bash
env_args=()
while IFS= read -r kv; do
  [ -n "$kv" ] && env_args+=(--env "$kv")
done < <(ak env claude @work2)
herdr pane split --current --direction right --cwd ../wt-lane1 --no-focus "${env_args[@]}"
```

4. Talk to the lane with the herdr-peers protocol (one ask, one reply, depth
   1, at most 4 open asks) when it is installed; otherwise with Herdr's own
   prompt command.
5. Verify and merge exactly as in the headless loop; close only the panes
   you created.

The permission opt-out applies inside panes too: a pane started through
`ak` inherits `AGENTKIT_PERMISSIONS=ask` when the user set it.

## Deep Work Plans

In a repository that runs Deep Work Plans (v7 contract), a plan marks the
tasks that may run in parallel as `parallel_safe` and grants delegation
explicitly. The plan's own agent is then the lead described here:

- it assigns one account per parallel task with `ak pick --count N`;
- headless tasks go through `ak run` in a worktree (the plan's agentkit
  addon), interactive ones through a Herdr pane (the plan's herdr addon);
- every delegation is recorded in the plan's journal before its result is
  used, and only the plan's own gate runner can close a task — a delegate's
  report never does.

If the repository has no such plan, ignore this section.
