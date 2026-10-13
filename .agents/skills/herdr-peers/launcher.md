# Launcher — starting a new peer (optional)

Use this only when the human or the plan asks for a new peer. Asking an agent
that already runs in a pane needs no launch: use `herdr-peers list` and
`herdr-peers ask`. The `herdr` commands below are only named here; their
options and JSON shapes are defined by Herdr's official skill.

Every launch follows the same three steps:

1. **Create a pane you own** — `herdr pane split` next to yours, with the
   working directory the peer should use (its own worktree when it will
   write: [discipline.md](discipline.md) §2). For a **one-shot delegate**,
   set `HERDR_PEERS_DEPTH=1` in its environment: it may reply or notify, but
   cannot ask. A **swarm lane** launched by a lead has no depth mark (remove
   an inherited `HERDR_PEERS_DEPTH`); it may ask the lead and sibling lanes.
   While holding an unanswered ask, either kind still cannot ask (depth 1).
   Read the new pane id from the JSON response.
2. **Start the agent** in that pane — `herdr agent start <name> --kind <kind>
   --pane <id>`. Use the kind the human asked for.
3. **Send the brief** — a one-shot delegate receives its task as an ask:
   `herdr-peers ask local:<id> "<self-contained brief>"`. Name the
   peer's own pane in the brief and tell it to pass `--pane <id>` on every
   `herdr-peers` call: a Codex peer cannot learn its pane from
   `HERDR_PANE_ID` (its commands run from a background server that carries
   the id of whichever pane started it). For a swarm lane, claim the lead
   before launching, then refresh its lane list once the agent is ready
   ([orchestra.md](orchestra.md) §1). Brief long-lived work under the plan's
   authorization; if you send an ask, the lane replies or declines it before
   making its own asks.

Record what you created; close the pane only when you are done with it, and
only because you created it.

## With an agent profile launcher (`ak env`)

When the `ak` command (coding-agents-kit) is installed, it can prepare the
environment for a named profile of a CLI. `ak env <kind> @<profile>` prints
`KEY=VALUE` lines — variable names and paths, never secret values — and prints
nothing for the CLI's own home. Pass each line to the pane as one `--env`:

```bash
# One-shot delegate; for a swarm lane start with env_args=() and no inherited depth mark.
env_args=(--env HERDR_PEERS_DEPTH=1)
while IFS= read -r kv; do
  [ -n "$kv" ] && env_args+=(--env "$kv")
done < <(ak env claude @work)
pane=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus "${env_args[@]}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
herdr agent start reviewer --kind claude --pane "$pane"
herdr-peers ask --profile work "local:$pane" "<brief>"
```

## Without `ak`

Start the agent with the CLI's own home — `herdr agent start <name> --kind
<kind> --pane <id>` — or, for a command that is not a recognized agent,
`herdr pane run <id> "<command>"`.

## Permissions

A launched peer runs with its CLI's **default permissions**. Never add a
permission-bypass or auto-approve flag on the peer's behalf; if the human
wants an autonomous peer, the human configures that explicitly (for example
through the profile launcher's own opt-in), and you record that they did.
