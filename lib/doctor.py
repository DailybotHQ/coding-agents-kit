"""`ak doctor [--json]` — what is installed and configured, never a secret.

The JSON form is interface 1 (docs/schema/doctor-v1.json), read by other
tools to decide whether ak is usable:
  interface, version, os, kinds{installed, version, logged_in, path, cli,
  provider}, profiles{cli: [names]}, keys[names set], permissions ask|auto,
  aliases{classic, custom}, herdr_hooks{cli: {@profile: present|absent}},
  env_file{path, exists, mode}, problems[]

Login is file presence (plus credential variable *names*); no credential
file is opened except Claude's .claude.json, which names the account and
holds no token. CLI versions come from `<cli> --version` (5 s timeout).
"""

import json
import os
import stat
import sys

import aliases
import common
import hooks
import kinds
import profiles
from common import AkError, EXIT_USAGE


def _cli_version(exe):
    if not exe:
        return None
    out = common._probe([exe, "--version"], timeout=5).strip().splitlines()
    return out[0].strip() if out else None


def _env_file_state():
    path = common.env_file()
    state = {"path": path, "exists": os.path.isfile(path), "mode": None}
    if state["exists"]:
        state["mode"] = "%03o" % stat.S_IMODE(os.stat(path).st_mode)
    return state


def _provider_key_names(model, env):
    bases = sorted(set(p["key"] for p in model.providers.values())
                   | set(c["profile_token_var"] for c in model.clis.values() if c.get("profile_token_var")))
    names = []
    for name in sorted(env):
        if not env.get(name):
            continue
        if any(name == b or name.startswith(b + "_") for b in bases):
            names.append(name)
    return names


def collect(model, env):
    problems = []
    raw_perm = (env.get("AGENTKIT_PERMISSIONS") or "auto").strip().lower()
    if raw_perm not in ("ask", "auto"):
        problems.append("AGENTKIT_PERMISSIONS must be 'ask' or 'auto'; launches refuse to start until it is fixed")
        raw_perm = "ask"
    exe_cache = {}
    version_cache = {}
    kinds_out = {}
    for name in model.kind_names():
        kind = model.kind(name)
        cli = kind.cli_name
        if cli not in exe_cache:
            exe_cache[cli] = common.resolve_executable(kind.cli, env)
            version_cache[cli] = _cli_version(exe_cache[cli])
        if kind.key_var:
            logged_in = bool(env.get(kind.key_var)) or (
                profiles.login_state(model, cli, "", env) if kind.key_optional else False)
        else:
            logged_in = profiles.login_state(model, cli, "", env)
        kinds_out[name] = {
            "cli": cli,
            "provider": kind.provider_name,
            "installed": exe_cache[cli] is not None,
            "path": exe_cache[cli],
            "version": version_cache[cli],
            "logged_in": logged_in,
        }
    prof = {cli: [] for cli in model.cli_names()}
    for cli, name, _directory in profiles.listing(model, env):
        prof[cli].append(name)
    herdr = {}
    for cli in model.cli_names():
        if not hooks.supported(model, cli):
            continue
        herdr[cli] = {"@default": hooks.presence(model, cli, "", env)}
        for name in prof[cli]:
            herdr[cli]["@" + name] = hooks.presence(model, cli, name, env)
    defaults = {}
    for cli in model.cli_names():
        try:
            setting = profiles.default_setting(cli, env)
        except AkError as exc:
            problems.append("%s; ak %s refuses to launch until it is fixed" % (exc, cli))
            continue
        if setting is None:
            continue
        defaults[cli] = profiles.default_label(setting)
        if setting not in ("", profiles.PICK) and setting not in prof[cli]:
            problems.append("%s=@%s names a profile that does not exist. Fix: ak profiles add %s @%s"
                            % (profiles.default_var(cli), setting, cli, setting))
    if common.os_name() == "linux" or _in_container(env):
        problems.extend(_stranded_logins(model, env, prof))
    alias_state = aliases.load()
    envfile = _env_file_state()
    if envfile["exists"] and envfile["mode"] not in ("600", "400") and common.os_name() != "windows":
        problems.append("%s is mode %s; it holds keys: chmod 600 it" % (envfile["path"], envfile["mode"]))
    return {
        "interface": common.INTERFACE,
        "version": common.VERSION,
        "os": common.os_name(),
        "kinds": kinds_out,
        "profiles": prof,
        "keys": _provider_key_names(model, env),
        "permissions": raw_perm,
        "aliases": {"classic": alias_state["classic"], "providers": alias_state.get("providers", False),
                    "custom": [a["name"] for a in alias_state["custom"]]},
        "herdr_hooks": herdr,
        "default_profiles": defaults,
        "env_file": envfile,
        "problems": problems,
    }


def _stranded_logins(model, env, prof):
    """On Linux or in a container: accounts whose file names the account but
    whose token is not here — a login kept in a macOS Keychain does not
    travel. One problem per account, with the fix."""
    out = []
    for cli in model.cli_names():
        if model.clis[cli].get("login", {}).get("token_files") is None:
            continue
        if not common.resolve_executable(model.clis[cli], env) and not prof[cli]:
            continue
        for name in [""] + prof[cli]:
            if not profiles.token_missing(model, cli, name, env):
                continue
            target = "ak %s%s" % (cli, " @" + name if name else "")
            portable = [n for n in prof[cli] if n != name and profiles.portable_login(model, cli, n, env)]
            fix = ("log in here (%s, then the CLI's login), or launch an account whose login is a file: "
                   "%s=@%s" % (target, profiles.default_var(cli), portable[0])) if portable else \
                  ("log in here: %s, then the CLI's login" % target)
            out.append("%s %s: the account is named here but its login token is not (a macOS Keychain login does "
                       "not travel to Linux or a container). Fix: %s" % (cli, profiles.label(name), fix))
    return out


def render_text(model, report):
    cw = max([len(c) for c in model.cli_names()] + [8])   # the CLI column
    out = []
    w = out.append
    w("agentkit %s (interface %d) on %s — %s" % (report["version"], report["interface"], report["os"], common.KIT_ROOT))
    ef = report["env_file"]
    w("env file: %s (%s)" % (ef["path"], ("mode " + ef["mode"]) if ef["exists"] else "missing — ./install.sh creates it"))
    w("permissions: %s%s" % (report["permissions"], "  (opt-out: no autonomy flag is added)"
                             if report["permissions"] == "ask" else
                             "  (default: every launch adds the CLI's autonomy flag; opt out with --ask"
                             " or AGENTKIT_PERMISSIONS=ask)"))
    w("")
    w("## CLIs")
    for cli in model.cli_names():
        k = report["kinds"][cli]
        login = {True: "logged in", False: "not logged in", None: "login: unknown"}[k["logged_in"]]
        if k["installed"]:
            w("  %-*s %-28s %s  (%s)" % (cw, cli, k["version"] or "?", login, k["path"]))
        else:
            w("  %-*s not installed — ak install %s" % (cw, cli, cli))
    w("")
    w("## Provider kinds")
    # One line per key: the kinds it serves, so an unset key is one line, not
    # one per kind. A kind whose CLI is missing says so; --json keeps the
    # per-kind detail.
    by_key = {}
    for name in model.kind_names():
        kind = model.kind(name)
        if kind.provider_name:
            by_key.setdefault(kind.key_var, []).append(name)
    width = max([len(key) for key in by_key] or [0])
    for key, names in sorted(by_key.items()):
        # Only the key itself: a kind whose key is optional is "logged in"
        # through its CLI's own login, which says nothing about the key.
        is_set = key in report["keys"]
        tags = []
        for n in names:
            note = "CLI not installed" if not report["kinds"][n]["installed"] else (
                "key optional" if model.kind(n).data.get("key_optional") else "")
            tags.append("%s (%s)" % (n, note) if note else n)
        w("  %-*s  %-6s %s" % (width, key, "set" if is_set else "unset", " ".join(tags)))
    if not report["keys"]:
        w("  ready once its key is set: ak env import <file>, or edit the env file")
    w("")
    w("## Keys (names only)")
    w("  " + (" ".join(report["keys"]) or "(none set)"))
    w("")
    w("## Profiles")
    any_profile = False
    for cli, names in sorted(report["profiles"].items()):
        if names:
            any_profile = True
            w("  %-*s %s" % (cw, cli, " ".join("@" + n for n in names)))
    if not any_profile:
        w("  (none — @default is each CLI's own home; ak profiles add claude @2)")
    for cli, setting in sorted(report.get("default_profiles", {}).items()):
        w("  %-*s default: ak %s -> %s (%s)" % (cw, cli, cli, setting, profiles.default_var(cli)))
    w("")
    w("## Aliases")
    w("  classic preset: %s%s" % ("on" if report["aliases"]["classic"] else "off",
                                 "" if report["aliases"]["classic"] else " (ak alias preset classic --on)"))
    if report["aliases"]["custom"]:
        w("  custom: " + " ".join(report["aliases"]["custom"]))
    w("")
    w("## Herdr hooks")
    for cli, states in sorted(report["herdr_hooks"].items()):
        w("  %-*s %s" % (cw, cli, " ".join("%s=%s" % (p, s) for p, s in sorted(states.items()))))
    if report["problems"]:
        w("")
        w("## Problems")
        for p in report["problems"]:
            w("  - " + p)
    return "\n".join(out) + "\n"


def main(model, args, env):
    as_json = False
    for arg in args:
        if arg == "--json":
            as_json = True
        else:
            raise AkError("usage: ak doctor [--json]", EXIT_USAGE)
    env = dict(env)
    report = collect(model, env)
    if as_json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        if _in_container(env):
            common.warn("inside a container — this reports the container's CLIs and config, not the host's")
        elif report["permissions"] == "auto":
            common.warn("autonomy is on and this is not a container — agents run commands without asking; "
                        "autonomy is meant for disposable or sandboxed environments (opt out: AGENTKIT_PERMISSIONS=ask)")
        sys.stdout.write(render_text(model, report))
    return 0


def _in_container(env):
    if os.path.exists("/.dockerenv"):
        return True
    return any(env.get(v) for v in ("REMOTE_CONTAINERS", "CODESPACES", "DEVCONTAINER")) or \
        env.get("container") in ("docker", "podman")
