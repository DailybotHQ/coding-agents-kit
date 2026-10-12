# Unattended lanes: launch, detect a blocked agent, escalate

Read this when the user wants lanes to run without them — launching new
agents on new accounts or folders without a per-launch approval — and has
said so. That instruction (or a plan's pre-authorization) is the
**standing grant** this page relies on. It covers launching; it never covers answering
a CLI's risk acknowledgement.

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
the bypass-permissions acknowledgement ("Bypass Permissions mode … accept
the risk"). **No agent ever answers it.** It is a one-time step the
developer takes per profile, when the profile is created: open
`ak claude @work2` once and accept it. A lane that stops there is escalated.

## 2. Detect a blocked lane

- `herdr agent list` — a lane that is `blocked`, or `idle` with no output
  after its prompt, needs a look.
- `herdr pane read <pane>` — read the screen before doing anything. Identify
  it by its text; if you cannot name it with certainty, it is unknown.

## 3. The one keystroke a lead may send

Only one screen, and only when `--trust-cwd` could not be used (an older
`ak`, a CLI launched some other way): the **folder-trust** screen of the
lane's own worktree, on a pane the lead launched itself.

| Screen | Answer |
| --- | --- |
| Claude: "Do you trust the files in this folder?" (No, exit preselected) | select "Yes, I trust this folder", then Enter |
| Codex: "Trust this folder?" | select the trust option, then Enter |

Grok ("Do you trust the contents of this directory?") names the
repository's main working tree, not the lane's worktree: it is not the
screen of the lane's own worktree, so never answer it. `ak grok … --trust-cwd`
(ak 0.6.1 and later) pre-trusts that folder; with an older `ak`, launch Grok
from the repository root, or treat the screen as blocked and reroute the
lane to another vendor.

Send the fewest keys that answer it with `herdr agent send-keys` (Herdr's
own skill defines the key names), then `herdr pane read <pane>` again to
confirm the agent moved on, and record it in your report to the user.

## 4. What always goes to the user

Never send keys for any other screen. Read it, record it, and tell the user:

- Claude's bypass-permissions acknowledgement — the developer accepts it
  once per profile;
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
