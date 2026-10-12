"""`--trust-cwd` / AGENTKIT_TRUST_CWD=1: mark the launch directory as trusted
in the profile's own CLI config before the CLI starts, so a new account does
not stop at the CLI's folder-trust screen.

Explicit opt-in only: nothing here runs without the flag or the variable.
The data is in providers.toml (`[clis.<cli>.trust]`: the file, relative to a
root, and its format); only the two edits are code:

- claude-json: `<account root>/.claude.json` gains
  projects[<abs cwd>].hasTrustDialogAccepted = true (read-modify-write,
  atomic, every other key and the file mode kept);
- codex-toml: `<home>/config.toml` gains `[projects."<abs cwd>"]` with
  trust_level = "trusted", appended only when that table is absent (an
  existing table, whatever it says, is the user's and is left alone);
- grok-toml: `<home>/trusted_folders.toml` gains `[folders."<abs root>"]`
  with trusted = true and decided_at = <epoch seconds>, the same append-only
  rule. grok asks about the repository, not the folder it was started in:
  the root is the main working tree of the git repository around the cwd
  (from a linked worktree, the repository it belongs to), else the cwd.

It never answers any other screen (the bypass-permissions warning, a login)
and never changes the permission posture. Portable: os.path only.
"""

import json
import os
import time

import common

ENV = "AGENTKIT_TRUST_CWD"


def requested(flag, env):
    return bool(flag) or env.get(ENV) == "1"


def _toml_key(path):
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise common.AkError("--trust-cwd: the folder name has a control character; not written", common.EXIT_USAGE)
    return '"%s"' % path.replace("\\", "\\\\").replace('"', '\\"')


def _write(path, text, confine):
    import writers
    try:
        writers._atomic_write(path, text, confine)   # follows a symlinked dotfile; stays inside the profile
    except writers.WriterError as exc:
        raise common.AkError("--trust-cwd: %s" % exc, common.EXIT_NOT_READY)


def _claude_json(path, cwd, confine):
    doc = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        try:
            doc = json.loads(text) if text.strip() else {}
        except ValueError:
            raise common.AkError("%s is not valid JSON; --trust-cwd leaves it alone" % path, common.EXIT_NOT_READY)
        if not isinstance(doc, dict):
            raise common.AkError("%s is not a JSON object; --trust-cwd leaves it alone" % path, common.EXIT_NOT_READY)
    projects = doc.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise common.AkError("%s: 'projects' is not an object; --trust-cwd leaves it alone" % path, common.EXIT_NOT_READY)
    entry = projects.setdefault(cwd, {})
    if not isinstance(entry, dict):
        raise common.AkError("%s: the entry for %s is not an object; --trust-cwd leaves it alone" % (path, cwd),
                             common.EXIT_NOT_READY)
    if entry.get("hasTrustDialogAccepted") is True:
        return False
    entry["hasTrustDialogAccepted"] = True
    _write(path, json.dumps(doc, indent=2) + "\n", confine)
    return True


def _codex_toml(path, cwd, confine):
    header = "[projects.%s]" % _toml_key(cwd)
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    if any(line.strip() == header for line in text.splitlines()):
        return False
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    _write(path, text + sep + header + '\ntrust_level = "trusted"\n', confine)
    return True


def _grok_toml(path, folder, confine):
    header = "[folders.%s]" % _toml_key(folder)
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    if any(line.strip() == header for line in text.splitlines()):
        return False
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    _write(path, text + sep + header + "\ntrusted = true\ndecided_at = %d\n" % int(time.time()), confine)
    return True


def _linked_root(top, gitfile):
    """The main working tree of a linked worktree (`.git` is a file naming
    <common>/worktrees/<name>, whose `commondir` names <common>), or None: a
    submodule (no commondir) or a bare repository (no main working tree)."""
    try:
        with open(gitfile, encoding="utf-8") as handle:
            text = handle.read()
        if not text.startswith("gitdir:"):
            return None
        gitdir = os.path.join(top, text[len("gitdir:"):].strip())
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as handle:
            common = os.path.realpath(os.path.join(gitdir, handle.read().strip()))
    except OSError:
        return None
    return os.path.dirname(common) if os.path.basename(common) == ".git" else None


def repo_root(cwd):
    """The folder a repository-scoped trust screen asks about (grok): walk up
    from cwd to the first `.git`; a directory -> its parent, a linked
    worktree -> its main working tree; no repository -> cwd. Files only (no
    git executable)."""
    here = cwd
    while True:
        dotgit = os.path.join(here, ".git")
        if os.path.isdir(dotgit):
            return here
        if os.path.isfile(dotgit):
            return _linked_root(here, dotgit) or here
        parent = os.path.dirname(here)
        if parent == here:
            return cwd
        here = parent


FORMATS = {"claude-json": _claude_json, "codex-toml": _codex_toml, "grok-toml": _grok_toml}
FOLDER = {"grok-toml": repo_root}      # default: the launch folder itself


def mark(prep, cwd):
    """Trust `cwd` for the prepared launch. Returns the file changed, or None
    (already trusted, or a CLI with no trust data — then a one-line note)."""
    spec = prep.kind.cli.get("trust")
    if not spec:
        common.warn("--trust-cwd: %s has no folder-trust screen ak knows; nothing written" % prep.kind.cli["name"])
        return None
    cwd = os.path.realpath(os.path.abspath(cwd))
    folder = FOLDER.get(spec["format"], lambda here: here)(cwd)
    path = prep.ctx.ref_path(spec["file"])
    confine = prep.directory if prep.profile else None
    if FORMATS[spec["format"]](path, folder, confine):
        common.warn("--trust-cwd: %s trusted in %s" % (folder, path))
        return path
    return None
