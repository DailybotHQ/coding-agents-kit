"""Account profiles: several accounts of the same CLI side by side.

`ak claude @work`, `ak codex @2 -c`. Profile 1 (no @, @1, @default) is the
CLI's own home: nothing is exported and nothing is created. Every other
profile lives in
    ${AGENTKIT_PROFILES_DIR:-~/.local/share/agentkit/profiles}/<cli>/<name>/
(mode 700) and the CLI is pointed at it through its own isolation knob
(providers.toml `isolation` + `home_env`). Kinds of the same CLI share a
profile: `ak claude @2` and `ak claude-glm @2` see the same sessions.

Ported from the private kit's lib/profiles.sh (its variables were renamed to
the AGENTKIT_ prefix); the behaviour is pinned by tests/scopes/profiles.sh.
No secret value is ever printed: errors name variables only.
"""

import os
import re
import shutil
import sys

import common
from common import AkError, EXIT_NOT_READY, EXIT_USAGE, EXIT_AGENT_FAILED

_NAME = re.compile(r"^[a-z0-9._-]+$")


def root():
    return os.environ.get("AGENTKIT_PROFILES_DIR") or os.path.join(common.data_dir(), "profiles")


def normalize(raw):
    """'Work' -> 'work', '02' -> '2', '1'/'default' -> '' (profile 1)."""
    name = raw.lower()
    if not name or len(name) > 32 or name.startswith(".") or not _NAME.match(name):
        raise AkError("\"@%s\" is not a profile name: use 1-32 letters, digits, '.', '_' or '-', not "
                      "starting with '.'. A prompt that starts with @ goes after --: ak <kind> -- @%s" % (raw, raw))
    if name.isdigit():
        name = str(int(name))
    if name in ("1", "default"):
        return ""
    return name


def label(name):
    return "@%s" % (name or "default")


def path(cli, name):
    return os.path.join(root(), cli, name)


def suffix(name):
    """'cliente-x' -> 'CLIENTE_X' (the provider key suffix)."""
    return re.sub(r"[^A-Z0-9_]", "_", name.upper())


def interactive():
    """Is there a person at a terminal to answer? AGENTKIT_ASSUME_TTY=1 lets
    the test suite drive the question through a pipe."""
    if os.environ.get("AGENTKIT_ASSUME_TTY") == "1":
        return True
    return sys.stdin.isatty() and sys.stderr.isatty()


def _ask(question):
    sys.stderr.write("ak: %s [y/N] " % question)
    sys.stderr.flush()
    answer = sys.stdin.readline().strip()
    return answer in ("y", "Y", "yes", "YES", "Yes")


def create(cli, name):
    directory = path(cli, name)
    cdir = os.path.join(root(), cli)
    if os.path.isdir(cdir):
        for other in os.listdir(cdir):
            if other != name and suffix(other) == suffix(name) and os.path.isdir(os.path.join(cdir, other)):
                raise AkError("@%s would share provider keys (*_%s) with the existing %s profile @%s; "
                              "choose another name" % (name, suffix(name), cli, other), EXIT_USAGE)
    old = os.umask(0o077)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise AkError("could not create %s: %s" % (directory, exc.strerror), common.EXIT_INTERNAL)
    finally:
        os.umask(old)
    for p in (root(), os.path.join(root(), cli), directory):
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass
    common.warn("created %s profile @%s at %s — log in inside the session" % (cli, name, directory))
    return directory


def ensure(cli, name, may_ask=True):
    """The profile directory; asks once to create an unknown profile."""
    if not name:
        return None
    directory = path(cli, name)
    if os.path.isdir(directory):
        return directory
    hint = "ak profiles add %s @%s" % (cli, name)
    if not may_ask or not interactive():
        raise AkError("%s profile \"@%s\" does not exist. Create it with: %s" % (cli, name, hint), EXIT_NOT_READY)
    if not _ask("%s profile \"@%s\" does not exist. Create it?" % (cli, name)):
        raise AkError("not created; nothing launched.", EXIT_AGENT_FAILED)
    return create(cli, name)


def existing(cli, name):
    """The directory of an existing profile, or an error naming `profiles add`."""
    if not name:
        return None
    directory = path(cli, name)
    if not os.path.isdir(directory):
        raise AkError("%s profile \"@%s\" does not exist. Create it with: ak profiles add %s @%s"
                      % (cli, name, cli, name), EXIT_NOT_READY)
    return directory


def mirror(real, fake, keep):
    """Link every entry of `real` except `keep` into `fake` (existing entries
    are left alone): a relocated HOME/XDG dir still shows git, gh, ssh."""
    os.makedirs(fake, exist_ok=True)
    if not os.path.isdir(real):
        return
    for entry in os.listdir(real):
        if entry == keep:
            continue
        target = os.path.join(fake, entry)
        if os.path.lexists(target):
            continue
        try:
            os.symlink(os.path.join(real, entry), target)
        except OSError:
            pass


def activate(cli_name, cli, name, directory, env):
    """Point the CLI at the profile (mutates env). Profile 1: no-op."""
    if not name:
        return
    real_home = env.get("HOME") or common.home()
    env["AGENTKIT_ACTIVE_PROFILE"] = "%s/%s" % (cli_name, name)
    isolation = cli["isolation"]
    if isolation == "env":
        env[cli["home_env"]] = directory
    elif isolation == "xdg":
        pairs = (("XDG_CONFIG_HOME", ".config", "config"), ("XDG_DATA_HOME", ".local/share", "data"),
                 ("XDG_STATE_HOME", ".local/state", "state"), ("XDG_CACHE_HOME", ".cache", "cache"))
        for var, default, sub in pairs:
            real = env.get(var) or os.path.join(real_home, default)
            mirror(real, os.path.join(directory, sub), "opencode")
            env[var] = os.path.join(directory, sub)
    elif isolation == "cursor-home":
        # Cursor keeps its login in a Keychain entry with a fixed name, so
        # only a separate HOME plus the file credential store keeps accounts
        # apart.
        fake_home = os.path.join(directory, "home")
        mirror(real_home, fake_home, ".cursor")
        os.makedirs(os.path.join(fake_home, ".cursor"), exist_ok=True)
        env["AGENTKIT_REAL_HOME"] = real_home
        env["HOME"] = fake_home
        env["AGENT_CLI_CREDENTIAL_STORE"] = "file"
        env["CURSOR_CONFIG_DIR"] = os.path.join(fake_home, ".cursor")


def apply_keys(kind, name, env, require=True):
    """Map the profile's provider key into the kind's key variable.

    Profile 1 reads <KEY>; a named profile reads <KEY>_<SUFFIX> into <KEY>
    and never falls back to profile 1's key. Companions (non-secret) follow
    the suffix when set. With require=False a missing key is not an error
    (callers that never use the value, e.g. `ak env`)."""
    var = kind.key_var
    if not var:
        return
    envfile = common.env_file()
    if name:
        sfx = suffix(name)
        src = "%s_%s" % (var, sfx)
        if env.get(src):
            env[var] = env[src]
        elif kind.key_optional or not require:
            env.pop(var, None)
        else:
            raise AkError("%s is not set (profile @%s has its own key and never uses %s). Add it to %s."
                          % (src, name, var, envfile), EXIT_NOT_READY)
        for comp in kind.provider.get("companions", []):
            csrc = "%s_%s" % (comp, sfx)
            if env.get(csrc):
                env[comp] = env[csrc]
    elif require and not kind.key_optional and not env.get(var):
        raise AkError("%s is not set. Add it to %s." % (var, envfile), EXIT_NOT_READY)


def strip_profile_keys(model, env, keep=()):
    """Remove every <KEY>_<SUFFIX> of the known providers: those are the
    kit's per-profile variables and never meaningful to a CLI."""
    keys = [p["key"] for p in model.providers.values()]
    for name in list(env):
        if name in keep:
            continue
        for key in keys:
            if name.startswith(key + "_"):
                env.pop(name, None)


# ------------------------------------------------------------- login probe

def login_state(model, cli_name, name, env):
    """True / False / None (cannot tell) from file presence and credential
    variable names only — no credential is ever read."""
    import kinds
    cli = model.clis[cli_name]
    login = cli.get("login", {})
    kind = model.kind(cli_name)
    directory = path(cli_name, name) if name else None
    ctx = kinds.Context(kind, env, env.get("HOME") or common.home(), profile_dir=directory)
    for ref in login.get("files", []):
        p = ctx.ref_path(ref)
        if os.path.isfile(p):
            marker = login.get("marker")
            if not marker:
                return True
            try:
                with open(p, "rb") as handle:
                    if marker.encode() in handle.read():
                        return True
            except OSError:
                pass
    if not name and any(env.get(v) for v in login.get("env", [])):
        return True
    if not login.get("definitive"):
        return None
    return False


def keys_by_name(model, cli_name, name, env):
    """'VAR=set' / 'VAR=unset' for the provider keys a CLI's kinds read."""
    out = []
    seen = []
    for kname in model.kind_names():
        kind = model.kind(kname)
        if kind.cli_name != cli_name or not kind.key_var or kind.key_var in seen:
            continue
        seen.append(kind.key_var)
    for var in sorted(seen):
        full = "%s_%s" % (var, suffix(name)) if name else var
        out.append("%s=%s" % (full, "set" if env.get(full) else "unset"))
    return out


# ------------------------------------------------------- `ak profiles …`

def _target(model, args, verb):
    if len(args) < 2:
        raise AkError("usage: ak profiles %s <cli> @name" % verb)
    cli_name = model.cli_of(args[0]) if args[0] in model.clis or args[0] in model.kinds else None
    if cli_name is None:
        raise AkError("unknown CLI '%s'. Use one of: %s (or a kind such as claude-glm)."
                      % (args[0], " ".join(model.cli_names())))
    if not args[1].startswith("@"):
        raise AkError("name the profile with @, e.g. ak profiles %s %s @2" % (verb, args[0]))
    return cli_name, normalize(args[1][1:])


def default_home(model, cli_name, env=None):
    import kinds
    env = env or os.environ
    ctx = kinds.Context(model.kind(cli_name), env, env.get("HOME") or common.home())
    return ctx.root("home")


def listing(model, env):
    rows = []
    base = root()
    for cli_name in model.cli_names():
        cdir = os.path.join(base, cli_name)
        if not os.path.isdir(cdir):
            continue
        for name in sorted(os.listdir(cdir)):
            directory = os.path.join(cdir, name)
            if not os.path.isdir(directory) or os.path.islink(directory):
                continue
            rows.append((cli_name, name, directory))
    return rows


def cmd_ls(model, env):
    rows = listing(model, env)
    print("%-9s %-14s %-6s %-40s %s" % ("CLI", "PROFILE", "LOGIN", "KEYS", "PATH"))
    for cli_name, name, directory in rows:
        state = login_state(model, cli_name, name, env)
        login = {True: "yes", False: "no", None: "?"}[state]
        keys = " ".join(keys_by_name(model, cli_name, name, env)) or "-"
        print("%-9s %-14s %-6s %-40s %s" % (cli_name, "@" + name, login, keys, directory))
    if not rows:
        print("(no profiles yet — @default is each CLI's own home; create one with: ak profiles add claude @2)")
    return 0


def cmd_add(model, args, env):
    cli_name, name = _target(model, args, "add")
    if not name:
        raise AkError("@default is the CLI's own home (%s); it always exists." % default_home(model, cli_name, env))
    directory = path(cli_name, name)
    if os.path.isdir(directory):
        print("%s profile @%s already exists: %s" % (cli_name, name, directory))
        return 0
    create(cli_name, name)
    return 0


def cmd_path(model, args, env):
    cli_name, name = _target(model, args, "path")
    if not name:
        print(default_home(model, cli_name, env))
        return 0
    directory = path(cli_name, name)
    if not os.path.isdir(directory):
        raise AkError("%s profile @%s does not exist (it would live at %s)" % (cli_name, name, directory),
                      EXIT_NOT_READY)
    print(directory)
    return 0


def cmd_rm(model, args, env):
    yes = any(a in ("-y", "--yes") for a in args)
    rest = [a for a in args if a not in ("-y", "--yes")]
    cli_name, name = _target(model, rest, "rm")
    if not name:
        raise AkError("refusing to remove @default: it is the CLI's own home (%s)."
                      % default_home(model, cli_name, env))
    directory = path(cli_name, name)
    if not os.path.isdir(directory) or os.path.islink(directory):
        raise AkError("%s profile @%s does not exist." % (cli_name, name), EXIT_NOT_READY)
    real_root = os.path.realpath(os.path.join(root(), cli_name))
    if os.path.realpath(directory) != os.path.join(real_root, name):
        raise AkError("refusing to remove %s: it resolves outside %s." % (directory, os.path.join(root(), cli_name)))
    if not yes:
        if not interactive():
            raise AkError("no terminal to confirm; rerun with --yes to remove %s" % directory)
        if not _ask("delete %s profile \"@%s\" (%s), with its sessions and login?" % (cli_name, name, directory)):
            common.warn("kept %s" % directory)
            return EXIT_AGENT_FAILED
    shutil.rmtree(os.path.realpath(directory))
    common.warn("removed %s profile @%s" % (cli_name, name))
    if cli_name == "claude":
        common.warn("Claude's token for that profile stays in the macOS Keychain (an entry named "
                    "\"Claude Code-credentials-<id>\"); delete it in Keychain Access if you want it gone.")
    return 0


def cmd_run(model, args, env):
    cli_name, name = _target(model, args, "run")
    command = args[2:]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise AkError("name the command to run, e.g. ak profiles run cursor @2 agent login")
    if name:
        directory = existing(cli_name, name)
        activate(cli_name, model.clis[cli_name], name, directory, env)
    # Same hygiene as a launch: no per-profile key variables; the opt-out is
    # inherited, autonomy is not exported.
    strip_profile_keys(model, env)
    if (env.get("AGENTKIT_PERMISSIONS") or "").strip().lower() != "ask":
        env.pop("AGENTKIT_PERMISSIONS", None)
    return exec_command(command, env)


def exec_command(argv, env):
    if os.name == "nt":  # Windows cannot replace the process: stay the parent, pass the status on
        import subprocess
        try:
            return subprocess.call(common.windows_argv(argv, env), env=env)
        except OSError as exc:
            raise AkError("%s failed to start: %s" % (argv[0], exc.strerror), EXIT_NOT_READY)
    exe = argv[0] if os.sep in argv[0] else common.which(argv[0], env)
    if not exe:
        raise AkError("%s: command not found" % argv[0], 127)
    os.execve(exe, argv, env)
    return 0  # not reached


def main(model, args, env):
    sub = args[0] if args else "ls"
    rest = args[1:]
    if sub in ("ls", "list"):
        return cmd_ls(model, env)
    if sub == "add":
        return cmd_add(model, rest, env)
    if sub == "path":
        return cmd_path(model, rest, env)
    if sub in ("rm", "remove"):
        return cmd_rm(model, rest, env)
    if sub == "run":
        return cmd_run(model, rest, env)
    if sub == "hooks":
        import hooks
        return hooks.cmd_hooks(model, rest, env)
    raise AkError("unknown profiles command '%s'. Use: ls | add <cli> @name | path <cli> @name | "
                  "run <cli> @name -- <command…> | rm <cli> @name [--yes] | hooks <cli> @name" % sub, EXIT_USAGE)
