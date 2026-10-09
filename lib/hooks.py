"""Herdr agent-state hooks inside profile directories.

`herdr integration install <cli>` writes its hook files into the CLI's own
home (~/.claude/hooks/…, ~/.codex/…, the OpenCode plugin dir, …). A profile
is a different home, so without them Herdr falls back to screen detection
for that profile. `ak profiles hooks <cli> @name` copies the installed files
into the profile and registers them there:

  * hook files (providers.toml [clis.<cli>.hooks].files) are copied, mode
    kept, with any occurrence of the CLI's own home rewritten to the
    profile's;
  * the registration file (`register`: Claude's settings.json, Codex's and
    Cursor's hooks.json) is merged: only entries that run
    herdr-agent-state are taken from the source, their paths rewritten, and
    they replace older herdr entries in the profile's file — every other
    key and hook of the profile is kept. A profile file that does not parse
    is refused and left untouched.

It reads the real home and writes only inside the profile; it never runs
Herdr and never writes the CLI's own home. Rerunning it is a no-op.
`ak doctor` reports presence per profile (herdr_hooks).
"""

import json
import os

import common
import kinds
from common import AkError, EXIT_NOT_READY, EXIT_USAGE

MARKER = "herdr-agent-state"


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


def _rewrite(text, pairs):
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def _herdr_entries(value):
    """Keep only the parts of a hooks structure that run herdr-agent-state."""
    return MARKER in json.dumps(value)


def _merge_registration(src_path, dst_path, pairs):
    """Merge herdr hook entries of src into dst. Returns True when written."""
    if not os.path.isfile(src_path):
        return False
    try:
        with open(src_path) as handle:
            src = json.load(handle)
    except ValueError as exc:
        raise AkError("cannot read Herdr's registration %s: %s" % (src_path, exc), EXIT_NOT_READY)
    dst = {}
    if os.path.exists(dst_path):
        try:
            with open(dst_path) as handle:
                raw = handle.read()
            dst = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            raise AkError("refusing to modify %s: not valid JSON (%s). Fix it by hand and retry." % (dst_path, exc),
                          EXIT_NOT_READY)
        if not isinstance(dst, dict):
            raise AkError("refusing to modify %s: the top level is not an object." % dst_path, EXIT_NOT_READY)
    src_hooks = src.get("hooks") if isinstance(src, dict) else None
    if not isinstance(src_hooks, dict):
        return False
    original = json.loads(json.dumps(dst))  # deep copy: `dst` is edited below
    hooks = dst.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise AkError("refusing to modify %s: 'hooks' is not an object." % dst_path, EXIT_NOT_READY)
    for event, entries in src_hooks.items():
        if not isinstance(entries, list):
            continue
        ours = [json.loads(_rewrite(json.dumps(e), pairs)) for e in entries if _herdr_entries(e)]
        if not ours:
            continue
        kept = [e for e in hooks.get(event, []) if not _herdr_entries(e)] if isinstance(hooks.get(event), list) else []
        hooks[event] = kept + ours
    merged = dict(dst)
    merged["hooks"] = hooks
    for key, value in src.items():  # e.g. Cursor's top-level "version"
        if key != "hooks" and key not in merged:
            merged[key] = value
    if merged == original and os.path.exists(dst_path):
        return False
    _write(dst_path, json.dumps(merged, indent=2) + "\n", 0o600)
    return True


def _write(path, text, mode):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        old = os.umask(0o077)
        try:
            os.makedirs(parent)
        finally:
            os.umask(old)
    import tempfile
    path = os.path.realpath(path)  # through a symlink (dotfiles), never replacing it
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix="." + os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _inside(path, root):
    real = os.path.realpath(path)
    root = os.path.realpath(root)
    return real == root or real.startswith(root + os.sep)


def cmd_hooks(model, args, env):
    import profiles
    if len(args) != 2 or not args[1].startswith("@"):
        raise AkError("usage: ak profiles hooks <cli> @name", EXIT_USAGE)
    try:
        cli_name = model.cli_of(args[0])
    except kinds.KindsError as exc:
        raise AkError(str(exc), EXIT_USAGE)
    name = profiles.normalize(args[1][1:])
    if not supported(model, cli_name):
        raise AkError("Herdr has no state-hook integration for %s; it detects that CLI from the screen." % cli_name,
                      EXIT_USAGE)
    if not name:
        raise AkError("@default is the CLI's own home: Herdr installs its hooks there itself "
                      "(herdr integration install %s)." % cli_name, EXIT_USAGE)
    directory = profiles.existing(cli_name, name)
    spec = model.clis[cli_name]["hooks"]
    src_ctx = _ctx(model, cli_name, "", env)
    dst_ctx = _ctx(model, cli_name, name, env)
    roots = sorted(set(ref.split(":", 1)[0] for ref in spec["files"] + ([spec["register"]] if spec.get("register") else [])))
    # Longest source first, so a nested root is never half-rewritten.
    pairs = sorted(((src_ctx.root(r), dst_ctx.root(r)) for r in roots), key=lambda p: -len(p[0]))
    sources = [(src_ctx.ref_path(ref), dst_ctx.ref_path(ref)) for ref in spec["files"]]
    missing = [s for s, _ in sources if not os.path.isfile(s)]
    if missing:
        raise AkError("Herdr's hooks for %s are not installed in its own home (%s missing). Install them first: "
                      "herdr integration install %s" % (cli_name, ", ".join(missing), cli_name), EXIT_NOT_READY)
    changed = 0
    for src, dst in sources:
        if not _inside(os.path.dirname(dst), directory) and not _inside(dst, directory):
            raise AkError("refusing to write %s: outside the profile %s" % (dst, directory), common.EXIT_INTERNAL)
        with open(src) as handle:
            text = _rewrite(handle.read(), pairs)
        mode = os.stat(src).st_mode & 0o755
        current = None
        if os.path.isfile(dst):
            with open(dst) as handle:
                current = handle.read()
        if current != text or (os.stat(dst).st_mode & 0o777) != mode:
            _write(dst, text, mode)
            print("copied %s -> %s" % (src, dst))
            changed += 1
    if spec.get("register"):
        src_reg = src_ctx.ref_path(spec["register"])
        dst_reg = dst_ctx.ref_path(spec["register"])
        if _merge_registration(src_reg, dst_reg, pairs):
            print("registered Herdr's hooks in %s" % dst_reg)
            changed += 1
    if not changed:
        print("%s @%s already has Herdr's hooks" % (cli_name, name))
    return 0
