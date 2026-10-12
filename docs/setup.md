# Set up the kit on any machine or container — `ak setup` and the `agentkit-setup` skill

Two pieces work together:

- The **skill** [`agentkit-setup`](../skills/agentkit-setup/SKILL.md) is what an agent follows to install, configure,
  verify, repair and upgrade the kit on a host (macOS, Linux, WSL, Windows) or in a container. It *decides with you*:
  it looks first, asks before each change, changes only what you agreed to, and checks at the end.
- The **helper** `ak setup` is the read-only, deterministic half the skill stands on, so it never guesses about a
  machine. It observes and renders; it never installs, repairs or decides, and it never writes anything except an
  explicit `--out FILE`.

Neither replaces the two commands you can always type yourself (`git clone --branch v0.6.0 …` and `install.sh`, see
[install](install.md)). They exist so an agent can do the same thing safely, repeatably and on a machine you are not
sitting at.

## Use the skill

```bash
npx --yes skills add DailybotHQ/coding-agents-kit@v0.6.0 --skill agentkit-setup
```

or let the kit print it: `ak --skill setup`. Then ask your agent, for example: *"set up coding-agents-kit on this
machine with a Claude and a Codex account"* or *"write a Dockerfile that runs the kit for the CI image"*.
The skill starts from a clone of the pinned tag, so it works before `ak` exists:

```bash
git clone --branch v0.6.0 https://github.com/DailybotHQ/coding-agents-kit
python3 coding-agents-kit/lib/ak.py setup probe --json
```

What it will ask you, once each, before it acts: installing a system package, editing a shell rc, the autonomy
posture, creating a profile, installing a coding-agent CLI (this uses the network), writing a recipe file into a
repository, uninstalling. It never asks for, reads, prints or stores a key or token: it tells you where the value
goes (`~/.config/agentkit/env`, or the container's environment or secrets) and checks only that the *name* is set.

## `ak setup probe [--json]`

What machine or container this is, and what is already there: OS, architecture, libc (`glibc`/`musl`), WSL, container
and CI signals, root, whether the home is writable, the shell, python, the tools it found (`git`, `bash`, `node`, `npm`,
`docker`, `herdr`, `pwsh`), an existing kit install (path, version, on PATH, installed with `--no-rc`), the env file
(path, mode, the **names** of the keys that are set), profiles, which CLIs are present, a `posture_hint` and a list of
`problems`. It runs from an uninstalled clone, changes nothing, and never executes a coding-agent CLI (running them
writes caches into your home); only `git`, `bash`, `node`, `docker` and `pwsh` are asked for `--version`, without any
key or token variable in their environment. JSON schema `setup-probe-v1` ([schema](schema/setup-probe-v1.json)).

`posture_hint` is a hint, never applied: `auto` inside a container or CI (where autonomy is designed to run),
`ask` on a personal host.

## `ak setup verify [--json] [--cli LIST] [--profile CLI=@a,@b] [--keys NAMES] [--expect-posture auto|ask]`

An ordered list of named checks, each `ok`, `warn` or `fail`, and for each failure the **one command that repairs it**
(or none when only you can act, such as a login or a key value). Exit 0 when nothing fails, 1 otherwise, 2 for a usage
error. It never applies a repair.

| Check | Fails when | Repair it names |
| --- | --- | --- |
| `install.marker` | no kit install is found | the installer command for this clone (`--no-rc` in a container or CI) |
| `install.version` | warn: the install is older than this code | the installer command |
| `path.ak` | warn: `ak` is not on PATH | the `export PATH=…` (or PowerShell) line |
| `python.version` | python is older than 3.9 | none: you install python |
| `envfile.exists` / `envfile.mode` | the env file is missing / readable by others | the installer / `chmod 600 <file>` |
| `cli.<name>.installed` (`--cli`) | the CLI is not on PATH | `ak install <name>` |
| `profile.<cli>.<name>.exists` / `.login` (`--profile`) | the profile is missing / has no login | `ak profiles add …` / the profile's login command |
| `keys.<NAME>.set` (`--keys`) | the variable is not set | none: you add the value to the env file |
| `posture.matches` (`--expect-posture`) | the posture differs from what you chose | a line for the env file |
| `aliases.rc` | warn: installed with `--no-rc` but a shell rc carries the kit's block | `ak alias rc --remove` |

JSON schema `setup-verify-v1` ([schema](schema/setup-verify-v1.json)).

## `ak setup docker`: container recipes

```bash
ak setup docker --ref v0.3.0 --sha256 <64 hex> [--base debian|ubuntu] [--cli claude,codex] [--user NAME] \
  [--format dockerfile|compose|entrypoint|devcontainer] [--out FILE]
```

It prints a recipe to stdout (or writes a **new** file with `--out`, never overwriting one). `--ref` must be a release
tag; `--sha256` is the digest of `coding-agents-kit-<tag>.tar.gz` from that release's `SHA256SUMS`: the helper never
invents one and never uses the network. What every recipe does, and checks on itself before it is printed:

- the base image is pinned by tag, the kit is installed from the **release tarball**, verified against the digest
  **before** it is unpacked, as a **non-root** user, with `--no-rc`;
- no key or token appears in an `ARG` or `ENV` and no fetch is piped into a shell; keys reach the container at run
  time (environment, `env_file` or secrets);
- config (`~/.config/agentkit`) and profiles are volumes, PATH is set by the image, a `HEALTHCHECK` runs
  `ak doctor --json`;
- `compose` passes key **names** through with no value; `entrypoint` sets `AGENTKIT_PERMISSIONS` from a variable;
  `devcontainer` is a minimal alternative: **prefer `dck`** (devcontainer-kit), whose images install this kit from the
  same pinned, verified tarball.

Alpine and other musl images are refused: the pinned CLI binaries are glibc builds and would not run.
npm-installed CLIs (`codex`, `opencode`, `pi`, `cline`) need a recent Node; `dck` ships a pinned one.

## Platforms

One code path everywhere; only what the probe finds differs. macOS and Linux (and WSL, treated as Linux) use
`install.sh`; Windows uses `install.ps1`, types `ak.cmd`, and starts the core as `py -3 <install>\lib\ak.py` from
programs (as for `ak run`). The env file keeps `KEY=value` lines: mode 600 on POSIX, current-user access on Windows.
CI runs the bash-free checks and a probe/verify smoke natively on Windows, and builds the container recipe with Docker.

Unverified here: running every flow on a real Windows or macOS machine, a read-only root filesystem, a rootless or
proxy-only network. They are listed as checks for you in the repository's verification notes rather than claimed.

## Troubleshooting

`ak setup verify` is the first step; each `fix:` line is the command. `ak setup probe` shows what changed since.
`musl` or an old python are stops, not things to work around. A failed digest check means the recipe's `--sha256`
does not match the tarball: re-read it from the release's `SHA256SUMS`, never skip it.
