# Unattended lanes: launch, detect a blocked agent, unblock it

Read this when the user wants lanes to run without them — launching new
agents on new accounts or folders and getting them past their first-run
screens — and has said so. That instruction (or a plan's pre-authorization)
is the **standing grant** this page relies on. Without it, every screen below
is the user's to answer.

## 1. Launch so nothing stops

A new account in a new folder stops at the CLI's folder-trust screen. Avoid
it instead of answering it:

```bash
git worktree add ../wt-lane1 -b lane/lane1
ak run claude @work2 --cwd ../wt-lane1 --trust-cwd --output-format json -- 'Implement the lane task; run its tests; commit.'
```

`--trust-cwd` (or `AGENTKIT_TRUST_CWD=1`, inherited by nested `ak`) marks
that folder as trusted in that profile's own config before the CLI starts
(Claude and Codex). It writes nothing without the flag, never answers any
other screen and never changes the permission posture. For an interactive
lane in a Herdr pane, start the agent the same way: `ak claude @work2
--trust-cwd` in the lane's worktree.

Claude shows one more screen the first time a profile runs with autonomy:
the bypass-permissions warning. `ak` never accepts it. The user accepts it
once per profile (`ak claude @work2`, then accept); when the user gave the
standing grant, the lead may accept it as described in step 3.

## 2. Detect a blocked lane

- `herdr agent list` — a lane that is `blocked`, or `idle` with no output
  after its prompt, needs a look.
- `herdr pane read <pane>` — read the screen before doing anything. Identify
  it by its text; if you cannot name it with certainty, it is unknown.

## 3. What the lead may answer with keys (standing grant only)

Only these, only on panes the lead created, only for the lane's own worktree:

| Screen | Answer |
| --- | --- |
| Claude: "Do you trust the files in this folder?" (No, exit preselected) | select "Yes, I trust this folder", then Enter |
| Codex: "Trust this folder?" | select the trust option, then Enter |
| Claude: bypass-permissions warning (first autonomous run of a profile) | accept — **never** when the user set `AGENTKIT_PERMISSIONS=ask` or launched with `--ask` |

Send the fewest keys that answer that screen with `herdr agent send-keys`
(Herdr's own skill defines the key names), then `herdr pane read <pane>`
again to confirm the agent moved on. Record what you answered in your report
to the user.

## 4. What always goes to the user

Never send keys for, and tell the user instead:

- a login, a credential, a token or an API-key prompt;
- a per-action permission request — that is the user's opt-out working;
- a destructive confirmation (delete, reset, force, overwrite);
- a payment, plan, billing or upgrade prompt;
- any screen you cannot name with certainty;
- a pane you did not create, or a folder that is not the lane's worktree.

Two failed attempts on one lane: stop the lane and report.

## 5. Limits

`ak` itself sends no keystrokes; it only performs the explicit `--trust-cwd`
write. Trusting a folder is not autonomy: the permission posture still comes
from the user (`--ask`, `AGENTKIT_PERMISSIONS=ask` win). A lane with
autonomy can change anything its worktree and its account reach, so give it
only its own worktree.
