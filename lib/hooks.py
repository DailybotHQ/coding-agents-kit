"""Herdr agent-state hooks inside profile directories.

`herdr integration install <cli>` writes its hook files into the CLI's own
home (~/.claude/hooks/…, ~/.codex/…, the OpenCode plugin dir, …). A profile
directory is a different home, so Herdr would fall back to screen detection
there. `ak profiles hooks <cli> @name` copies the installed files into the
profile (never writing the real home); `ak doctor` reports presence.
Which files, per CLI, is data: providers.toml [clis.<cli>.hooks].
"""

import os

import common
import kinds


def supported(model, cli_name):
    return bool(model.clis[cli_name].get("hooks", {}).get("files"))


def _ctx(model, cli_name, name, env):
    import profiles
    directory = profiles.path(cli_name, name) if name else None
    return kinds.Context(model.kind(cli_name), env, env.get("HOME") or common.home(), profile_dir=directory)


def presence(model, cli_name, name, env):
    """'present' when every hook file is in that home, else 'absent'."""
    ctx = _ctx(model, cli_name, name, env)
    files = model.clis[cli_name]["hooks"]["files"]
    return "present" if all(os.path.isfile(ctx.ref_path(ref)) for ref in files) else "absent"
