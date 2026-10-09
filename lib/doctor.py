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
    bases = sorted(set(p["key"] for p in model.providers.values()))
    names = []
    for name in sorted(env):
        if not env.get(name):
            continue
        if any(name == b or name.startswith(b + "_") for b in bases):
            names.append(name)
    return names


def collect(model, env):
    problems = []
    raw_perm = (env.get("AGENTKIT_PERMISSIONS") or "ask").strip().lower()
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
    alias_state = aliases.load()
    envfile = _env_file_state()
    if envfile["exists"] and envfile["mode"] not in ("600", "400"):
        problems.append("%s is mode %s; it holds keys: chmod 600 it" % (envfile["path"], envfile["mode"]))
    return {
        "interface": common.INTERFACE,
        "version": common.VERSION,
        "os": common.os_name(),
        "kinds": kinds_out,
        "profiles": prof,
        "keys": _provider_key_names(model, env),
        "permissions": raw_perm,
        "aliases": {"classic": alias_state["classic"], "custom": [a["name"] for a in alias_state["custom"]]},
        "herdr_hooks": herdr,
        "env_file": envfile,
        "problems": problems,
    }


def render_text(model, report):
    out = []
    w = out.append
    w("agentkit %s (interface %d) on %s — %s" % (report["version"], report["interface"], report["os"], common.KIT_ROOT))
    ef = report["env_file"]
    w("env file: %s (%s)" % (ef["path"], ("mode " + ef["mode"]) if ef["exists"] else "missing — ./install.sh creates it"))
    w("permissions: %s%s" % (report["permissions"], "  (pass-through: no autonomy flag is added)"
                             if report["permissions"] == "ask" else "  (every launch adds the CLI's autonomy flag)"))
    w("")
    w("## CLIs")
    for cli in model.cli_names():
        k = report["kinds"][cli]
        login = {True: "logged in", False: "not logged in", None: "login: unknown"}[k["logged_in"]]
        if k["installed"]:
            w("  %-9s %-28s %s  (%s)" % (cli, k["version"] or "?", login, k["path"]))
        else:
            w("  %-9s not installed — ak install %s" % (cli, cli))
    w("")
    w("## Provider kinds")
    for name in model.kind_names():
        kind = model.kind(name)
        if not kind.provider_name:
            continue
        k = report["kinds"][name]
        key = "%s %s" % (kind.key_var, "set" if k["logged_in"] else "unset")
        w("  %-16s %-14s %s" % (name, "ready" if k["installed"] and k["logged_in"] else "not ready", key))
    w("")
    w("## Keys (names only)")
    w("  " + (" ".join(report["keys"]) or "(none set)"))
    w("")
    w("## Profiles")
    any_profile = False
    for cli, names in sorted(report["profiles"].items()):
        if names:
            any_profile = True
            w("  %-9s %s" % (cli, " ".join("@" + n for n in names)))
    if not any_profile:
        w("  (none — @default is each CLI's own home; ak profiles add claude @2)")
    w("")
    w("## Aliases")
    w("  classic preset: %s%s" % ("on" if report["aliases"]["classic"] else "off",
                                 "" if report["aliases"]["classic"] else " (ak alias preset classic --on)"))
    if report["aliases"]["custom"]:
        w("  custom: " + " ".join(report["aliases"]["custom"]))
    w("")
    w("## Herdr hooks")
    for cli, states in sorted(report["herdr_hooks"].items()):
        w("  %-9s %s" % (cli, " ".join("%s=%s" % (p, s) for p, s in sorted(states.items()))))
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
    env.pop("AGENTKIT_ENV_FILE_VARS", None)
    report = collect(model, env)
    if as_json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        if _in_container(env):
            common.warn("inside a container — this reports the container's CLIs and config, not the host's")
        sys.stdout.write(render_text(model, report))
    return 0


def _in_container(env):
    if os.path.exists("/.dockerenv"):
        return True
    return any(env.get(v) for v in ("REMOTE_CONTAINERS", "CODESPACES", "DEVCONTAINER")) or \
        env.get("container") in ("docker", "podman")
