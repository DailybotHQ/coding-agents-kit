# Flow D — configure

Ask what the user wants; do only that; verify afterwards.

## CLIs

`ak install` (no names) lists each CLI as missing or present with how it would be installed: a pinned vendor version, verified against a digest before anything runs.
`[GATE: CLI install]` — it downloads software onto the machine:
```bash
ak install codex pi
```
npm-installed CLIs (codex, opencode, pi, cline) need Node and npm; offering to install them is a `[GATE: system package]`.

## Accounts (profiles)

`[GATE: profile]` A profile is a separate login for the same CLI; the user logs in inside it:
```bash
ak profiles add claude @work
ak profiles run cursor @2 -- agent login
```
Profiles live in `~/.local/share/agentkit/profiles/<cli>/<name>` (mode 700). `@default` is the CLI's own home.

Claude, once per profile, by the user: the first launch with autonomy shows Claude's bypass-permissions acknowledgement. Tell the user to open `ak claude @work` once, right after creating the profile, and accept it themselves. No agent ever answers that screen; lanes that run unattended later need this done first.

## Provider keys — names only

Z.AI (`ZAI_CODING_API_KEY`), Azure (`AZURE_OPENAI_API_KEY` plus resource and model) and xAI (`XAI_API_KEY`) keys go in the env file, per profile as `<KEY>_<SUFFIX>` (`@work` → `_WORK`). Say the *name* and the *file*; the user types the value themselves. Never ask them to paste it, never open the file to read it. Confirm with `ak setup verify --keys ZAI_CODING_API_KEY`: it answers set or unset.

## Aliases

`ak alias preset classic --on` recreates shortcuts for the old wrappers and `ak alias preset providers --on` the provider ones. Only on request; they edit the rc block (`[GATE: shell rc]`).

## Posture

`[GATE: posture]` Autonomy is the kit's default. A container, VM or CI job is where it is meant to run; on a personal host recommend `AGENTKIT_PERMISSIONS=ask`. Record the choice only after they agree (a line in the env file or the container environment), then `ak setup verify --expect-posture ask|auto`.
