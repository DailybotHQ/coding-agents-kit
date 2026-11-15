# `ak update` — a verified vendor update, one CLI at a time

`ak update [<kind-or-cli>…] [--version VERSION] [--take-over] [--json]` brings
a CLI to the vendor's newest release without waiting for a kit release to
move the pin, with exactly the verification `ak install` applies. Without
arguments it updates every CLI that has a vendor discovery channel.

## Why it exists

Vendor CLIs update themselves, and their in-CLI update actions assume they
own the binary on PATH. Under ak that assumption breaks in a specific way:
ak launches whatever PATH resolves first, and the CLI's own update action
often writes a copy PATH does not resolve — codex's "Update now" runs
`npm install -g`, which lands in npm's prefix while PATH still resolves an
earlier vendor-managed symlink; Claude's native updater manages
`~/.local/share/claude/versions` and `~/.local/bin/claude` itself. The
result is an update prompt that keeps coming back no matter how often it is
accepted. `ak update` closes that loop: it installs the verified newest
release, makes sure PATH actually resolves it, and moves the kit's pin so
doctor, `ak install` and the next update agree.

## What it does, per CLI

1. **Discover** the newest version from the vendor (providers.toml
   `install.latest`):
   - `kind = "npm"` — the registry's `dist-tags.latest` document (codex,
     opencode, pi, cline), verified against its `dist.integrity` (sha512).
   - `kind = "manifest"` — the vendor's channel file naming the newest
     version, then that version's `manifest.json` (claude), verified against
     its per-platform digests, mapped back through `install.platforms`.
   - No `latest` table (cursor, grok, antigravity: trust-on-first-use
     digests) — skipped; move the pin with `scripts/update-pins.sh`.
2. **Verify** exactly like `ak install`. A digest mismatch refuses before
   anything is installed and before the pin moves.
3. **Install** through the channel itself: `npm install -g` of the verified
   tarball, or the verified binary written over `~/.local/bin/<executable>`
   (a regular file there is first backed up to `<name>.agentkit-orig`).
4. **Resolve** — the update only counts when PATH resolves the new release.
   A vendor-managed **symlink** is replaced only with `--take-over`, which
   prints what it pointed at; a **regular file** is never replaced by a
   link. An install whose copy stays shadowed is reported as such and the
   pin does not move.
5. **Re-pin** — the verified version and digests are written back into this
   kit's `providers.toml` atomically (parsed before it replaces the old
   file; the previous file is kept as `providers.toml.bak`), so `ak doctor`,
   `ak install` and the next `ak update` describe the same pin.

## Refusals

- A discovered version **older than the pin** is refused (a kit release may
  deliberately pin ahead); pass `--version` to name a downgrade on purpose.
- PATH already resolving a **newer** build than the vendor's newest (an
  unusual vendor channel state) is refused — the command does not downgrade
  your machine.
- **Fetched values that are not plain data refuse the whole update** before
  anything runs: a version or digest carrying a quote, a newline or any
  character a TOML string cannot hold is refused (providers.toml is never
  written with injected configuration, and the fetched digests must be
  `sha512-<base64>` or 64 hex).
- No vendor manifest → the CLI is skipped; the pin moves only through
  `scripts/update-pins.sh` (maintainer, digests re-derived from the source).

## Trust, and never unattended

The **metadata** (`dist-tags.latest`, the channel file, the release
manifest) comes from the same source the vendor's own installers trust; the
**artifact** is always checked against the fetched digests before it is
installed, and a pin moves only after this run has seen the vendor's
artifact match them — including the no-install "current" path, which
verifies the artifact before re-pinning. A concurrent run is held out by a
lock file next to providers.toml (a stale lock older than ten minutes is
removed once; anything fresher refuses). `ak update` is a human-invoked
installer action: agents, daemons and unattended loops never run it on
their own, the same rule that keeps autopilot away from installs.

## JSON

`ak update --json` prints one `update-v1` document
(`docs/schema/update-v1.json`): per CLI, the channel, the pin it came from,
the version discovered, what PATH resolves afterwards, whether the pin
moved, and a status — `updated`, `current` (PATH already resolved it; at
most the pin moved), `skipped` (nothing done) or `failed`. The install's own
output goes to stderr in that mode. Exit status: `0` when every requested
CLI ended `updated` or `current`; `3` when any failed, or when a CLI you
named by hand was skipped.

## Examples

```bash
ak update codex                    # newest verified codex, re-pins providers.toml
ak update claude --take-over       # replace Claude's own ~/.local/bin/claude link
ak update codex --version 0.169.0  # a named release (allows a downgrade on purpose)
ak update --json codex             # one update-v1 document for scripts
```

The machine case that names this command: `~/.local/bin/codex` is codex's
own standalone link while `npm install -g` keeps refreshing a shadowed
Homebrew copy. `ak update codex` installs the verified release into npm's
prefix; add `--take-over` once to point `~/.local/bin/codex` at it, and
`ak doctor` then shows the kit's pin and PATH agreeing.

## Restore

`--take-over` replaces only a symlink and prints its target: restore it with
`ln -sf <target> <link>` or by rerunning the vendor's installer. Replaced
regular files stay next to the new binary as `<name>.agentkit-orig`. The
previous providers.toml stays as `providers.toml.bak` until the next update.
