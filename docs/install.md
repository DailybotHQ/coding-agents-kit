# Install

## The kit

macOS, Linux, WSL (and Git Bash):

```bash
git clone --branch v0.2.0 https://github.com/DailybotHQ/coding-agents-kit
./coding-agents-kit/install.sh
```

Windows (PowerShell 5.1 or 7):

```powershell
git clone --branch v0.2.0 https://github.com/DailybotHQ/coding-agents-kit
.\coding-agents-kit\install.ps1
```

Requirements: bash and **python3 ≥ 3.9** (standard library only). Nothing
else; no package is downloaded.

What the installer does — and nothing more:

| | macOS / Linux (`install.sh`) | Windows (`install.ps1`) |
| --- | --- | --- |
| Program | `~/.local/share/agentkit/{bin,lib,skills,docs,providers.toml}` (dir mode 700) | `$HOME\.local\share\agentkit\…` with `bin\ak.cmd`, `bin\agentkit.cmd` |
| Env file | `~/.config/agentkit/env` from a template, mode 600, **only if missing** | `$HOME\.config\agentkit\env`, readable by you only, only if missing |
| PATH | one guarded block in your shell rc (see below); `--no-rc` skips it | your **user** Path; `-NoPath` skips it |
| Upgrade | rerun it: components are replaced, stale files removed | rerun it |
| Uninstall | `./install.sh --uninstall` | `.\install.ps1 -Uninstall` |

It never overwrites the env file, never touches `profiles/`, never installs
a coding-agent CLI and never uses the network. `--uninstall` keeps the env
file and your profiles. `AGENTKIT_HOME` moves the install, `AGENTKIT_ENV`
the env file. The install directory must be the kit's own: the installers
refuse a non-empty directory without their marker (`.agentkit-install`),
so `AGENTKIT_HOME=~/.local` can never wipe `~/.local/bin`.

**Scripts, CI and containers** use `./install.sh --no-rc` and call
`~/.local/share/agentkit/bin/ak` by path (or put that directory on PATH).

### The shell rc block

`install.sh` (and `ak alias`) add exactly one guarded block to each
existing `~/.zshrc` / `~/.bashrc` (and the rc of `$SHELL`; `~/.profile` when
there is none). It is replaced in place on every run and removed by
`--uninstall` or `ak alias rc --remove`, leaving the rest of the file as it
was (shown with `$HOME` for your home directory; the real block holds the
absolute path):

```sh
# >>> agentkit >>>
# Managed by coding-agents-kit (install.sh, ak alias). Edit outside this block.
if [ -d '$HOME/.local/share/agentkit/bin' ]; then case ":$PATH:" in *:$HOME/.local/share/agentkit/bin:*) ;; *) PATH='$HOME/.local/share/agentkit/bin':"$PATH"; export PATH ;; esac; fi
[ -f '$HOME/.local/share/agentkit/aliases.sh' ] && . '$HOME/.local/share/agentkit/aliases.sh'
# <<< agentkit <<<
```

`ak alias rc --print` shows it. After `install.sh --no-rc` (remembered) or
with `AGENTKIT_NO_RC=1`, `ak alias` never writes it — you source
`aliases.sh` yourself, or run `ak alias rc --install` when you want it. A
symlinked rc (dotfiles repo) is edited where it points. On macOS, a bash
login shell reads `~/.bash_profile`, not `~/.bashrc`: source `~/.bashrc` from
it if you use bash there.

### Windows notes

The python core runs natively (`ak.cmd` → `py -3 lib\ak.py`). **Programs
and scripts that call ak on Windows must run `py -3 <install>\lib\ak.py …`
directly**: `ak.cmd`, like every batch file, lets `cmd.exe` re-parse its
arguments, which is fine for what you type but unsafe for text that comes
from elsewhere (a prompt from another agent). Two other differences from
macOS/Linux: the env file is read as plain `KEY=value`
lines (no shell code), and `ak alias` targets POSIX shells only — use
`ak <kind>` instead of the `classic` aliases. Profiles of Cursor and
OpenCode link your other dotfiles into the profile home with symlinks,
which Windows allows only with Developer Mode or elevated rights; without
them those links are skipped.

## The coding-agent CLIs: `ak install`

```bash
ak install                 # what is installed, what is missing, and how each would be installed
ak install codex pi        # install those two if missing
ak install --all           # every missing CLI
```

Every CLI is pinned to an exact version and **verified before anything
runs or is installed**. Installed CLIs are skipped (never upgraded, moved or
removed); one failure never stops the others (exit 1 at the end).

| CLI | Channel | Pin | Digest source |
| --- | --- | --- | --- |
| claude | native binary → `~/.local/bin/claude` | `2.1.295` | sha256 per platform, from the vendor's release manifest |
| codex | npm tarball → `npm install -g <file>` | `0.158.0` | the registry's `integrity` (sha512) |
| cursor | package tarball → `~/.local/share/cursor-agent/versions/<v>`, linked as `cursor-agent` and `agent` | `2026.10.01-e373342` | sha256 per platform, recorded when the pin was taken (the vendor publishes none) |
| opencode | npm tarball | `1.18.31` | registry `integrity` |
| pi | npm tarball, `--ignore-scripts` | `0.85.1` | registry `integrity` |
| cline | npm tarball | `3.0.70` | registry `integrity` |
| grok | native binary → `~/.local/bin/grok` | `1.0.50` | sha256 per platform, recorded when the pin was taken (the vendor publishes none) |

Downloads go over HTTPS only (`curl --proto =https --tlsv1.2`, or python's
`urllib` without curl) into a private temporary directory. A digest that
does not match refuses the install and leaves nothing behind; a platform
with no pinned digest (Windows, for the native binaries) is refused with
the vendor's docs link; archives are unpacked only after every entry is
checked to stay inside its directory. Vendor install scripts are never run.
For npm, the verified tarball is what npm installs; its dependencies are
resolved by npm from the registry, each checked against the registry's own
integrity. After install, each CLI's own updater may take over; the pins are
what a fresh machine gets.

A CLI that cannot be pinned is stated in the data as
`unverified = "<reason>"` and installs only with
`ak install --allow-unverified <cli>`. No shipped CLI needs it.

Maintainers move a pin with `bash scripts/update-pins.sh`: it re-derives
every digest from its source and reports any difference.

npm channels need Node (`ak install` names how to get it when npm is
missing).

## Keys from another env file: `ak env import`

```bash
ak env import ~/path/to/old.env   # copy KEY=value lines into ~/.config/agentkit/env
```

For a move from another tool's env file. It copies `KEY=value` (and
`export KEY=value`) lines into the kit's env file (`AGENTKIT_ENV` when
set), appended under a dated comment and written as single-quoted
literals. It imports plain data only: it never overwrites a key the file
already sets, and skips empty values, lines that are not assignments and
values a shell would interpret (`$(…)`, backquotes, `$`, `;`, `&`, `|`,
unquoted spaces) — the env file is sourced, so copy those by hand only if
you trust them. It keeps profile-suffixed keys
(`<KEY>_<SUFFIX>`) as they are, and keeps the destination mode 600. It
refuses a source that other users can write. It prints only variable
**names**: what it imported and what it skipped, with the reason. Check the
imported names against the kinds you use (`ak doctor` lists the key
variables it sees) before deleting the old file.

## Aliases: `ak alias`

```bash
ak alias add w claude @work          # w  -> ak claude @work
ak alias add careful codex --ask     # careful -> ak codex --ask (always asks)
ak alias rm w
ak alias                             # list
ak alias preset classic --on         # claudex codexx cursorx opencodex pix clinex grokx
```

Aliases are shell functions in `~/.local/share/agentkit/aliases.sh`
(definitions in `~/.config/agentkit/aliases.json`), calling this kit's `ak`
by absolute path. Names are 1–32 letters, digits or `_` (portable to every
POSIX shell) and may not shadow `ak`, `agentkit` or a CLI ak launches.

The **`classic` preset** recreates the predecessor kit's wrapper names as
plain shortcuts for `ak <kind>`, for muscle memory and existing docs. They
follow your posture: autonomy by default, or the opt-out
(`AGENTKIT_PERMISSIONS=ask`). It ships **off** (see
[permissions](permissions.md)).
