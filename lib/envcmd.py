"""`ak env <kind> [@profile]` — the profile's environment as KEY=VALUE lines.
`ak env import <file>` — bring keys from another env file into the kit's.

Purpose: let another launcher (Herdr: `herdr pane split --env KEY=VALUE …`
then `herdr agent start --kind <kind>`) start the raw CLI in a profile.

Contract (interface 1):
  * stdout carries only KEY=VALUE lines: no `export`, no quoting;
  * no secret value, ever: provider keys are not printed (the kind's
    secret-bearing variables are named on stderr instead);
  * exit 0 with no output means "the CLI's own home" (@default of a
    canonical kind).
"""

import datetime
import os
import stat
import sys

import common
import launch
from common import AkError, EXIT_USAGE

# Variables that are the kit's own bookkeeping, not the CLI's environment.
INTERNAL = ("AGENTKIT_ACTIVE_PROFILE", "AGENTKIT_REAL_HOME")


def compute(model, kind_name, head, env):
    """(lines, notes): the KEY=VALUE pairs and the stderr notes."""
    import kinds
    before = dict(env)
    prep = launch.prepare(model, kind_name, head, env, purpose="print")
    changed = {}
    for name, value in prep.env.items():
        if before.get(name) != value and name not in INTERNAL:
            changed[name] = value
    # apply_keys may have mapped a key in memory; it is never printed. When
    # it removed one (optional key, named profile), print it empty so the
    # pane cannot inherit profile 1's key.
    blank = []
    if prep.kind.key_var:
        changed.pop(prep.kind.key_var, None)
        if before.get(prep.kind.key_var) and prep.kind.key_var not in prep.env:
            blank.append(prep.kind.key_var)
    provider_env, skipped = kinds.provider_env(prep.kind, prep.ctx, include_secret=False)
    changed.update(provider_env)
    for name in blank:
        changed[name] = ""
    lines = []
    for name in sorted(changed):
        value = changed[name]
        if (common.secret_like(name) and value) or "\n" in value:
            continue
        lines.append("%s=%s" % (name, value))
    notes = []
    if skipped or prep.kind.key_var and not prep.kind.key_optional:
        names = skipped or [prep.kind.key_var]
        notes.append("%s is not printed (it carries the %s key). Launch the kind itself in the pane "
                     "instead: ak %s %s" % (", ".join(names), prep.kind.key_var, kind_name,
                                            "@" + prep.profile if prep.profile else ""))
    extra = []
    if prep.kind.data.get("args"):
        extra.append("its arguments (%s)" % " ".join(a for a in prep.kind.data["args"] if "{key}" not in a))
    if prep.kind.data.get("writer"):
        extra.append("the provider config ak writes before launch")
    if prep.kind.data.get("pre"):
        extra.append("`%s %s` before launch" % (prep.kind.executable, prep.kind.data["pre"][0]))
    if extra:
        notes.append("%s also needs %s, which an environment cannot carry: run `ak %s%s` in the pane"
                     % (kind_name, " and ".join(extra), kind_name, " @" + prep.profile if prep.profile else ""))
    return lines, notes


IMPORT_USAGE = "usage: ak env import <file>"


def _assigned_name(raw):
    """The variable a KEY=value line assigns, or None for anything else."""
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    name, sep, _ = line.partition("=")
    name = name.strip()
    if not sep or not name or not name.replace("_", "").isalnum() or name[0].isdigit():
        return None
    return name


def _value_is_empty(raw):
    value = raw.split("=", 1)[1].strip()
    return value in ("", "''", '""')


def import_file(source, env):
    """Copy KEY=value lines from `source` into the env file. Never
    overwrites a key, never prints a value; returns (imported, skipped)
    where skipped is a list of (name or line number, reason)."""
    dest = env.get("AGENTKIT_ENV") or os.path.join(env.get("HOME") or common.home(), ".config", "agentkit", "env")
    try:
        st = os.stat(source)
    except OSError as exc:
        raise AkError("cannot read %s: %s" % (source, exc.strerror), EXIT_USAGE)
    if not stat.S_ISREG(st.st_mode):
        raise AkError("%s is not a regular file" % source, EXIT_USAGE)
    if os.name != "nt" and st.st_mode & 0o022:
        raise AkError("refusing %s: mode %o lets other users change it; fix it first (chmod 600 %s)"
                      % (source, stat.S_IMODE(st.st_mode), source), EXIT_USAGE)
    if os.path.exists(dest) and os.path.samefile(source, dest):
        raise AkError("%s is already the kit's env file" % source, EXIT_USAGE)
    with open(source) as fh:
        lines = fh.read().splitlines()
    present = set()
    if os.path.exists(dest):
        with open(dest) as fh:
            present = {n for n in (_assigned_name(line) for line in fh.read().splitlines()) if n}
    imported, skipped, out = [], [], []
    for number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name = _assigned_name(raw)
        if name is None:
            skipped.append(("line %d" % number, "not a KEY=value line (shell code is not imported)"))
        elif name in present:
            skipped.append((name, "already set in %s" % dest))
        elif _value_is_empty(raw):
            skipped.append((name, "empty"))
        else:
            present.add(name)
            imported.append(name)
            out.append(stripped)
    if out:
        directory = os.path.dirname(dest)
        if not os.path.isdir(directory):
            os.makedirs(directory, 0o700)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write("\n# imported from %s by `ak env import` on %s\n" % (source, datetime.date.today().isoformat()))
            fh.write("\n".join(out) + "\n")
        if os.name != "nt":
            os.chmod(dest, 0o600)
    return dest, imported, skipped


def main_import(args, env):
    if len(args) != 1 or args[0].startswith("-"):
        raise AkError(IMPORT_USAGE, EXIT_USAGE)
    dest, imported, skipped = import_file(args[0], env)
    print("imported into %s: %s" % (dest, ", ".join(imported) if imported else "nothing"))
    for what, why in skipped:
        print("skipped %s: %s" % (what, why))
    return 0


def main(model, args, env):
    if args and args[0] == "import":
        return main_import(args[1:], env)
    if not args or args[0].startswith("-"):
        raise AkError("usage: ak env <kind> [@profile]", EXIT_USAGE)
    kind_name = args[0]
    if kind_name not in model.kinds:
        raise AkError("unknown kind '%s'. Kinds: %s" % (kind_name, " ".join(model.kind_names())), EXIT_USAGE)
    rest = args[1:]
    if len(rest) > 1 or (rest and not rest[0].startswith("@")):
        raise AkError("usage: ak env <kind> [@profile]", EXIT_USAGE)
    head = launch.Head()
    if rest:
        head.profile_token = rest[0]
    elif env.get("AGENTKIT_PROFILE"):
        head.profile_token = env["AGENTKIT_PROFILE"] if env["AGENTKIT_PROFILE"].startswith("@") \
            else "@" + env["AGENTKIT_PROFILE"]
        head.profile_from_env = True
    lines, notes = compute(model, kind_name, head, dict(env))
    for note in notes:
        sys.stderr.write("ak env: %s\n" % note)
    for line in lines:
        sys.stdout.write(line + "\n")
    return 0
