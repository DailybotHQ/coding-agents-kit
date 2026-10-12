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


def create(cli, name, note=None):
    """Create the profile directory (mode 700). note: the CLI's
    `login.profile_note`, printed after the creation line."""
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
    if note:
        common.warn(note.replace("{suffix}", suffix(name)))
    return directory


def ensure(cli, name, may_ask=True, note=None):
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
    return create(cli, name, note)


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
        # XDG_STATE_HOME moves into the profile: keep the kit's own state
        # (usage cache, leases; lib/state.py) machine-wide.
        if not env.get("AGENTKIT_STATE_DIR"):
            env["AGENTKIT_STATE_DIR"] = os.path.join(env.get("XDG_STATE_HOME") or os.path.join(real_home, ".local/state"), "agentkit")
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
    elif isolation == "home":
        # The CLI keeps its state in one dot-directory of HOME and offers no
        # variable to move it: the profile gets a HOME of its own, with every
        # other entry of the real HOME linked in (git, ssh, gh keep working).
        fake_home = os.path.join(directory, "home")
        mirror(real_home, fake_home, cli["home_dir"])
        os.makedirs(os.path.join(fake_home, cli["home_dir"]), exist_ok=True)
        env["AGENTKIT_REAL_HOME"] = real_home
        env["HOME"] = fake_home


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


def token_var(cli, name):
    """The per-profile login token variable of a CLI for profile `name`
    (CLAUDE_CODE_OAUTH_TOKEN for @default, CLAUDE_CODE_OAUTH_TOKEN_<SUFFIX>
    for @name), or None when the CLI declares none."""
    base = cli.get("profile_token_var")
    if not base:
        return None
    return "%s_%s" % (base, suffix(name)) if name else base


def apply_token(cli, name, env):
    """A named profile gets its own token as the CLI's variable, or none at
    all: it never inherits @default's token. @default is left as it is."""
    base = cli.get("profile_token_var")
    if not base or not name:
        return
    own = env.get(token_var(cli, name))
    if own:
        env[base] = own
    else:
        env.pop(base, None)


def strip_profile_keys(model, env, keep=()):
    """Remove every <KEY>_<SUFFIX> of the known providers: those are the
    kit's per-profile variables and never meaningful to a CLI."""
    keys = [p["key"] for p in model.providers.values()]
    # A login token variable is stripped only for the suffixes of existing
    # profiles: a vendor variable that merely shares the prefix stays.
    tokens = set()
    for cli_name, pname, _d in listing(model, env):
        base = model.clis[cli_name].get("profile_token_var")
        if base:
            tokens.add("%s_%s" % (base, suffix(pname)))
    for name in list(env):
        if name in tokens and name not in keep:
            env.pop(name, None)
            continue
        if name in keep:
            continue
        for key in keys:
            if name.startswith(key + "_"):
                env.pop(name, None)


# ------------------------------------------------------- default profile

DEFAULT_PREFIX = "AGENTKIT_DEFAULT_PROFILE_"
PICK = "pick"
PORTABLE_LOGINS = ("file", "token-var")     # a Keychain login stays on its Mac


def default_var(cli_name):
    """AGENTKIT_DEFAULT_PROFILE_<CLI>: the account a bare `ak <cli>` uses."""
    return DEFAULT_PREFIX + suffix(cli_name)


def default_setting(cli_name, env):
    """The CLI's default profile setting: None (unset: the CLI's own home),
    PICK, or a profile name ('' = @default, the CLI's own home). `pick` is
    the opt-in fallback; `@pick` is a profile named pick."""
    var = default_var(cli_name)
    raw = (env.get(var) or "").strip()
    if not raw:
        return None
    if raw.lower() == PICK:
        return PICK
    name = raw[1:] if raw.startswith("@") else raw
    try:
        return normalize(name)
    except AkError:
        raise AkError("%s=%s is not a profile: use @<profile>, @default or pick" % (var, raw), EXIT_USAGE)


def default_label(setting):
    return PICK if setting == PICK else label(setting)


def resolve_default(model, kind, env):
    """The profile name a launch without @profile (and without
    AGENTKIT_PROFILE) uses: the CLI's AGENTKIT_DEFAULT_PROFILE_<CLI>, for
    its canonical kind only (a provider kind such as claude-glm reads its
    key per profile, so it keeps the CLI's own home). Returns (name, var)
    with var None when no default applied."""
    if kind.name != kind.cli_name:
        return "", None
    setting = default_setting(kind.cli_name, env)
    var = default_var(kind.cli_name)
    if setting is None:
        return "", None
    if setting != PICK:
        return setting, var
    name, room = pick_default(model, kind.cli_name, env)
    if name is None:
        common.warn("%s=pick: no %s account with a portable login has room; using @default" % (var, kind.cli_name))
        return "", var
    common.warn("%s=pick chose %s%s" % (var, label(name), "" if room is None else " (headroom %s%%)" % room))
    return name, var


def portable_login(model, cli_name, name, env):
    return login_kind(model, cli_name, name, env) in PORTABLE_LOGINS


def pick_default(model, cli_name, env, now=None):
    """The `pick` fallback: among the CLI's accounts with a portable login
    (a login file or a token variable, never a Keychain item), the one with
    the most headroom, by `ak pick`'s own policy (read-only). Returns
    (name or None, headroom_pct or None)."""
    import pick
    import usage
    rows = [r for r in usage.enumerate_rows(model, env) if r.cli == cli_name
            and portable_login(model, cli_name, _name_of(r.profile), env)]
    if not rows:
        return None, None
    now = usage.common_now() if now is None else now
    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in usage.fetch_all(rows, env, None, now)]
    chosen, _candidates, _soonest = pick.choose(results, allow_unknown=True, now=now)
    if not chosen:
        return None, None
    return _name_of(chosen[0]["profile"]), chosen[0]["headroom_pct"]


def _name_of(profile_label):
    return "" if profile_label == "@default" else profile_label[1:]


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
    if name and env.get(token_var(cli, name) or ""):
        return True
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
    if name and any(env.get("%s_%s" % (v, suffix(name))) for v in login.get("env", [])):
        return True
    if keychain_has(login.get("keychain"), env, ctx):
        return True
    if not login.get("definitive"):
        return None
    return False


def keychain_has(entries, env, ctx=None):
    """True when one of the CLI's macOS Keychain login items exists, None
    when the Keychain cannot be asked here (AGENTKIT_KEYCHAIN=off, or no
    `security` tool on macOS), False otherwise. An entry applies to the
    default home only, unless it sets `profile = true`: the CLI then names
    the item `<service>-<first 8 hex of sha256(config dir)>` for a profile
    directory (and for a default home moved by its home variable), as
    Claude does. Only presence is asked — `security find-generic-password`
    without -w never returns the secret, and its output is discarded.
    AGENTKIT_KEYCHAIN=off skips it (the test suite never touches the real
    Keychain)."""
    services = keychain_services(entries, ctx)
    if not services or common.os_name() != "macos":
        return False
    if env.get("AGENTKIT_KEYCHAIN") == "off":
        return None
    security = common.which("security", env)
    if not security:
        return None
    import subprocess
    clean = {k: v for k, v in env.items() if not common.secret_like(k)}
    for service, account in services:
        argv = [security, "find-generic-password", "-s", service]
        if account:
            argv += ["-a", account]
        try:
            proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL, timeout=5, env=clean)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    return False


def keychain_services(entries, ctx=None):
    """(service, account) pairs a home's Keychain login items are named by
    (see keychain_has); empty when no entry applies to this home."""
    import hashlib
    out = []
    profile_dir = ctx.profile_dir if ctx is not None else None
    home_env = ctx.kind.cli.get("home_env") if ctx is not None else None
    moved = ctx.env.get(home_env) if ctx is not None and home_env else None
    for entry in entries or []:
        service = entry["service"]
        directory = profile_dir or moved
        if directory and entry.get("profile"):
            service = "%s-%s" % (service, hashlib.sha256(directory.encode("utf-8")).hexdigest()[:8])
        elif profile_dir and not entry.get("shared"):
            continue          # `shared = true`: one item serves every home of the CLI (Antigravity)
        out.append((service, entry.get("account")))
    return out


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
    token = token_var(model.clis[cli_name], name)
    if token:
        out.append("%s=%s" % (token, "set" if env.get(token) else "unset"))
    return out


# ------------------------------------------------------- `ak profiles …`

def _target(model, args, verb):
    if len(args) < 2:
        raise AkError("usage: ak profiles %s <cli> @name" % verb)
    name = model.canonical(args[0])
    cli_name = model.cli_of(name) if name in model.clis or name in model.kinds else None
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


def login_kind(model, cli_name, name, env):
    """How an account is logged in, by presence only (no credential is read):
    token-var, file, keychain, none, or unknown when the CLI cannot tell."""
    import kinds
    cli = model.clis[cli_name]
    login = cli.get("login", {})
    if env.get(token_var(cli, name) or "") or (not name and any(env.get(v) for v in login.get("env", []))) \
            or (name and any(env.get("%s_%s" % (v, suffix(name))) for v in login.get("env", []))):
        return "token-var"
    kind = model.kind(cli_name)
    ctx = kinds.Context(kind, env, env.get("HOME") or common.home(), profile_dir=path(cli_name, name) if name else None)
    account = False
    for ref in login.get("files", []):
        p = ctx.ref_path(ref)
        if os.path.isfile(p):
            marker = login.get("marker")
            try:
                with open(p, "rb") as handle:
                    if not marker or marker.encode() in handle.read():
                        account = True
                        break
            except OSError:
                pass
    # `token_files`: the account file names the account, the token lives in
    # one of these files or in the Keychain (Claude: `.claude.json` versus
    # `.credentials.json`), so only a token file is a file login.
    token_files = login.get("token_files")
    if token_files is None and account:
        return "file"
    if any(os.path.isfile(ctx.ref_path(ref)) for ref in token_files or []):
        return "file"
    in_keychain = keychain_has(login.get("keychain"), env, ctx)
    if in_keychain:
        return "keychain"
    if in_keychain is None and account:
        return "unknown"        # the Keychain could not be asked; the account file alone cannot tell
    return "none" if login.get("definitive") else "unknown"


def token_missing(model, cli_name, name, env):
    """True when the account file names an account but no token is here: no
    token file and no token variable (Claude's `.claude.json` without
    `.credentials.json`). On Linux or in a container this is a login that
    stayed behind in a macOS Keychain. Presence only."""
    import kinds
    cli = model.clis[cli_name]
    login = cli.get("login", {})
    if login.get("token_files") is None or login_kind(model, cli_name, name, env) != "none":
        return False
    ctx = kinds.Context(model.kind(cli_name), env, env.get("HOME") or common.home(),
                        profile_dir=path(cli_name, name) if name else None)
    for ref in login.get("files", []):
        p = ctx.ref_path(ref)
        try:
            with open(p, "rb") as handle:
                if not login.get("marker") or login["marker"].encode() in handle.read():
                    return True
        except OSError:
            pass
    return False


# The first bytes of an executable built for each OS (ELF; Mach-O 32/64 bit,
# both byte orders, and universal binaries).
NATIVE_MAGIC = {
    "linux": (b"\x7fELF",),
    "macos": (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
               b"\xca\xfe\xba\xbe"),
}


def _runs_here(p):
    """True when p is an executable file this OS can run: a script, or a
    binary built for this OS (a macOS binary in a Linux container is not)."""
    if not os.path.isfile(p) or not os.access(p, os.X_OK):
        return False
    magic = NATIVE_MAGIC.get(common.os_name())
    if magic is None:
        return True
    try:
        with open(p, "rb") as handle:
            head = handle.read(4)
    except OSError:
        return False
    return head.startswith(b"#!") or head in magic


def daemon_state(cli, ctx, env):
    """The CLI's recorded background daemon (providers.toml `daemon`), by
    presence only: None when the CLI declares none; off when its variable is
    1; missing when the home records a daemon whose executable is not here or
    not built for this OS (a home shared with another machine); present; or
    absent when nothing is recorded (the CLI installs its own)."""
    daemon = cli.get("daemon")
    if not daemon:
        return None
    if (env.get(daemon["env"]) or "").strip() == "1":
        return "off"
    if _runs_here(ctx.ref_path(daemon["executable"])):
        return "present"
    return "missing" if os.path.lexists(ctx.ref_path(daemon["record"])) else "absent"


def daemon_args(cli, ctx, env):
    """The flags that turn the daemon off, when it is off or missing."""
    return list(cli["daemon"]["off"]) if daemon_state(cli, ctx, env) in ("off", "missing") else []


def daemon_marker(cli, ctx, env):
    """The flags that hand the launch's account marker to a daemon this launch
    reuses (present): its tool shells keep the environment of whoever started
    it, not this launch's (`ak capacity --self` would name nobody, or another
    kind). A daemon this launch starts inherits the marker; none when off."""
    daemon = cli.get("daemon") or {}
    account = env.get("AGENTKIT_ACTIVE_ACCOUNT")
    if not daemon.get("marker") or not account or daemon_state(cli, ctx, env) != "present":
        return []
    return [arg.replace("{account}", account) for arg in daemon["marker"]]


def set_names(model, cli_name, name, env):
    """The NAMES of the provider keys and login token this account would read
    that are set (never a value)."""
    return sorted(entry.split("=", 1)[0] for entry in keys_by_name(model, cli_name, name, env) if entry.endswith("=set"))


def portable(model, env):
    """profiles-v1: every account, names and kinds only, no absolute path."""
    out = []
    for cli_name in model.cli_names():
        cli = model.clis[cli_name]
        if common.resolve_executable(cli, env):
            out.append({"cli": cli_name, "profile": "@default", "path_relative": None, "isolation": cli["isolation"],
                        "login": login_kind(model, cli_name, "", env), "key_names_set": set_names(model, cli_name, "", env)})
    for cli_name, name, _directory in listing(model, env):
        cli = model.clis[cli_name]
        out.append({"cli": cli_name, "profile": "@" + name, "path_relative": "%s/%s" % (cli_name, name),
                    "isolation": cli["isolation"], "login": login_kind(model, cli_name, name, env),
                    "key_names_set": set_names(model, cli_name, name, env)})
    for row in out:
        try:
            setting = default_setting(row["cli"], env)
        except AkError:
            setting = None
        if setting not in (None, PICK) and label(setting) == row["profile"]:
            row["default"] = True       # what a bare `ak <cli>` launches (additive; `pick` marks none)
    order = {c: i for i, c in enumerate(model.cli_names())}
    out.sort(key=lambda r: (order[r["cli"]], r["profile"] != "@default", r["profile"]))
    return {"schema": "profiles-v1", "interface": common.INTERFACE, "profiles": out}


def cmd_ls(model, env, as_json=False):
    if as_json:
        import json
        sys.stdout.write(json.dumps(portable(model, env), indent=2, sort_keys=True) + "\n")
        return 0
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
    create(cli_name, name, model.clis[cli_name].get("login", {}).get("profile_note"))
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
    # The running account for `ak capacity --self`; an inherited marker would
    # name the outer account. A CLI here, as AGENTKIT_ACTIVE_PROFILE does.
    env["AGENTKIT_ACTIVE_ACCOUNT"] = "%s/%s" % (cli_name, label(name))
    apply_token(model.clis[cli_name], name, env)   # its own login token or none, never @default's
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
    as_json = bool(args) and args[0] == "--json"
    if as_json:
        args = args[1:]
    sub = args[0] if args else "ls"
    rest = args[1:]
    if sub in ("ls", "list"):
        as_json = as_json or rest == ["--json"]
        if rest and rest != ["--json"]:
            raise AkError("ak profiles ls takes no arguments (only --json)", EXIT_USAGE)
        return cmd_ls(model, env, as_json)
    if as_json:
        raise AkError("--json applies to ak profiles [ls] only", EXIT_USAGE)
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
