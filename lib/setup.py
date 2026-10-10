"""`ak setup probe|verify|docker` — the deterministic, read-only half of the
agentkit-setup skill.

    ak setup probe [--json]        what machine or container is this, what is installed
    ak setup verify [--json] ...   ordered checks, each with the exact repair command
    ak setup docker ...            render a pinned, verified, non-root container recipe

Every subcommand observes or renders; none decides for the person and none
applies a repair. They work from an uninstalled clone
(`python3 <clone>/lib/ak.py setup …`), which is how the skill looks at a
machine before it installs anything.

Secret discipline: provider keys are reported by variable name only; no
environment value is ever printed.

Portable on purpose (Linux, macOS, Windows, WSL): os.path, platform and
subprocess only; the OS decisions sit in `Host`, which tests replace to
simulate other systems.
"""

import json
import os
import platform
import re
import stat
import sys

import common
import doctor
import profiles
from common import AkError, EXIT_OK, EXIT_USAGE

PROBE_SCHEMA = "setup-probe-v1"
VERIFY_SCHEMA = "setup-verify-v1"
TOOLS = ("git", "bash", "node", "npm", "docker", "herdr", "pwsh")
# Only these are ever executed (`--version`): they keep no state. Vendor
# coding-agent CLIs are NEVER executed by the probe - running them writes
# caches and config into the home directory (observed), which would break the
# read-only promise. They are reported present/absent from PATH alone.
VERSION_PROBES = ("git", "bash", "node", "docker", "pwsh")
CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "JENKINS_URL", "TF_BUILD")
CONTAINER_VARIABLES = ("REMOTE_CONTAINERS", "CODESPACES", "DEVCONTAINER")
USAGE = """usage: ak setup probe [--json]
       ak setup verify [--json] [--cli LIST] [--profile CLI=@a,@b ...] [--keys NAMES] [--expect-posture auto|ask]
       ak setup docker --ref TAG --sha256 HEX [--base debian|ubuntu|alpine] [--cli LIST] [--user NAME]
                       [--format dockerfile|compose|entrypoint|devcontainer] [--out FILE]
Read-only helpers of the agentkit-setup skill: they observe and render, never install, repair or write
(except an explicit --out, which never overwrites).
"""


# ------------------------------------------------------------------ host

class Host(object):
    """The machine facts the probe reads. Tests subclass it (or set
    attributes) to simulate Linux, macOS, Windows, WSL, musl, containers."""

    def __init__(self, env):
        self.env = env

    def os_name(self):
        return common.os_name()

    def machine(self):
        return platform.machine()

    def exists(self, path):
        return os.path.exists(path)

    def read_text(self, path, limit=65536):
        try:
            with open(path, "rb") as handle:
                return handle.read(limit).decode("utf-8", "replace")
        except OSError:
            return ""

    def libc_family(self):
        family = platform.libc_ver()[0]
        return family or ""

    def musl_loader(self):
        for pattern_dir in ("/lib", "/usr/lib"):
            try:
                if any(name.startswith("ld-musl-") for name in os.listdir(pattern_dir)):
                    return True
            except OSError:
                continue
        return False

    def euid(self):
        getter = getattr(os, "geteuid", None)
        return getter() if getter else None

    def which(self, name):
        return common.which(name, self.env)

    def version_of(self, path):
        out = common._probe([path, "--version"], timeout=5).strip().splitlines()
        return out[0].strip()[:80] if out else None

    def home(self):
        return self.env.get("HOME") or self.env.get("USERPROFILE") or common.home()

    def python_version(self):
        return platform.python_version(), sys.version_info >= (3, 9)

    def writable(self, path):
        return os.access(path, os.W_OK)


# ----------------------------------------------------------------- probe

def _arch(machine):
    m = (machine or "").lower()
    return {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m or "unknown")


def _libc(host, os_name):
    if os_name != "linux":
        return "n/a"
    if host.musl_loader():
        return "musl"
    family = host.libc_family().lower()
    return "glibc" if family == "glibc" else "unknown"


def _container(host):
    signals = []
    if host.exists("/.dockerenv"):
        signals.append("dockerenv")
    for name in CONTAINER_VARIABLES:
        if host.env.get(name):
            signals.append(name)
    if host.env.get("container") in ("docker", "podman"):
        signals.append("container")
    cgroup = host.read_text("/proc/1/cgroup").lower()
    if any(word in cgroup for word in ("docker", "kubepods", "containerd", "libpod")):
        signals.append("cgroup")
    return {"detected": bool(signals), "signals": signals}


def _shell(host, os_name):
    shell = host.env.get("SHELL")
    if shell:
        return os.path.basename(shell.replace("\\", "/")) or None
    if os_name == "windows":
        if host.env.get("PSModulePath"):
            return "powershell"
        if host.env.get("ComSpec"):
            return "cmd"
    return None


def _cli_present(model, host, cli_name):
    """Is the CLI on PATH? By name only: nothing is executed. Cursor ships as
    `cursor-agent` (a bare `agent` is also Grok's name, and telling them apart
    means running them, which the probe does not do)."""
    cli = model.clis[cli_name]
    names = ["cursor-agent"] if cli.get("resolver") == "cursor" else [cli["executable"]]
    return any(host.which(name) for name in names)


def _install(host, env):
    root = env.get("AGENTKIT_HOME") or os.path.join(host.home(), ".local", "share", "agentkit")
    marker = os.path.join(root, ".agentkit-install")
    found = host.exists(marker)
    version = None
    if found:
        match = re.search(r'^VERSION\s*=\s*"([^"]+)"', host.read_text(os.path.join(root, "lib", "common.py")), re.M)
        version = match.group(1) if match else None
    return {"found": found, "path": root if found else None, "version": version,
            "on_path": host.which("ak") is not None,
            "no_rc": (host.exists(os.path.join(root, ".no-rc")) if found else None)}


def _env_file(host, env, model):
    path = env.get("AGENTKIT_ENV") or os.path.join(host.home(), ".config", "agentkit", "env")
    exists = host.exists(path)
    mode = None
    if exists and host.os_name() != "windows":
        try:
            mode = "%03o" % stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            mode = None
    return {"path": path, "exists": exists, "mode": mode, "keys": doctor._provider_key_names(model, env)}


def _posture_hint(container, ci, os_name):
    if container["detected"]:
        return {"value": "auto", "reason": "inside a container: autonomy is what the kit is designed for here"}
    if ci:
        return {"value": "auto", "reason": "a CI environment: disposable, autonomy is the designed default"}
    return {"value": "ask", "reason": "a personal host (%s): the kit recommends opting out with AGENTKIT_PERMISSIONS=ask unless you accept agents acting without asking" % os_name}


def collect(model, env, host=None):
    host = host or Host(env)
    os_name = host.os_name()
    libc = _libc(host, os_name)
    container = _container(host)
    ci = any(env.get(name) for name in CI_VARIABLES)
    py_version, py_ok = host.python_version()
    tools = {}
    for name in TOOLS:
        path = host.which(name)
        tools[name] = {"found": path is not None, "version": host.version_of(path) if path and name in VERSION_PROBES else None}
    clis = {}
    for cli_name in model.cli_names():
        clis[cli_name] = {"installed": _cli_present(model, host, cli_name), "version": None}
    prof = {cli: [] for cli in model.cli_names()}
    for cli_name, name, _directory in profiles.listing(model, env):
        prof[cli_name].append(name)
    euid = host.euid()
    home = host.home()
    env_file = _env_file(host, env, model)
    problems = []
    if not py_ok:
        problems.append("python 3.9 or newer is required (found %s)" % py_version)
    if not tools["git"]["found"]:
        problems.append("git was not found: installing from a pinned clone needs it")
    if os_name == "linux" and libc == "musl":
        problems.append("musl libc: the pinned CLI binaries are glibc builds and will not run here")
    if not host.writable(home):
        problems.append("the home directory is not writable: the kit cannot install or keep profiles")
    if env_file["mode"] is not None and env_file["mode"] not in ("600", "400"):
        problems.append("the env file is mode %s and holds keys: chmod 600 it" % env_file["mode"])
    return {
        "schema": PROBE_SCHEMA,
        "interface": common.INTERFACE,
        "version": common.VERSION,
        "os": os_name,
        "arch": _arch(host.machine()),
        "libc": libc,
        "wsl": bool(os_name == "linux" and (env.get("WSL_DISTRO_NAME") or "microsoft" in host.read_text("/proc/version").lower())),
        "container": container,
        "ci": ci,
        "root": (euid == 0) if euid is not None else None,
        "home_writable": bool(host.writable(home)),
        "shell": _shell(host, os_name),
        "python": {"version": py_version, "ok": bool(py_ok)},
        "tools": tools,
        "install": _install(host, env),
        "env_file": env_file,
        "profiles": prof,
        "clis": clis,
        "posture_hint": _posture_hint(container, ci, os_name),
        "problems": problems,
    }


def render_probe(report):
    out = []
    w = out.append
    w("agentkit setup probe (kit code %s, interface %d)" % (report["version"], report["interface"]))
    w("system:   %s %s, libc %s%s%s" % (report["os"], report["arch"], report["libc"], ", WSL" if report["wsl"] else "",
                                         ", root" if report["root"] else ""))
    c = report["container"]
    w("where:    %s%s%s" % ("container (%s)" % ", ".join(c["signals"]) if c["detected"] else "no container signal",
                            ", CI" if report["ci"] else "", ", home not writable" if not report["home_writable"] else ""))
    w("shell:    %s; python %s%s" % (report["shell"] or "unknown", report["python"]["version"], "" if report["python"]["ok"] else " (too old)"))
    w("tools:    " + "  ".join("%s=%s" % (n, "yes" if t["found"] else "no") for n, t in sorted(report["tools"].items())))
    i = report["install"]
    w("install:  %s" % ("kit %s at %s%s%s" % (i["version"] or "?", i["path"], "" if i["on_path"] else " (ak not on PATH)",
                                               "; installed with --no-rc" if i["no_rc"] else "") if i["found"] else "no kit install found"))
    e = report["env_file"]
    w("env file: %s (%s); keys set (names): %s" % (e["path"], ("mode " + e["mode"]) if e["exists"] and e["mode"] else ("present" if e["exists"] else "missing"),
                                                   " ".join(e["keys"]) or "none"))
    w("CLIs:     " + "  ".join("%s=%s" % (n, "yes" if c2["installed"] else "no") for n, c2 in sorted(report["clis"].items())))
    profile_list = ["%s:%s" % (cli, " ".join("@" + n for n in names)) for cli, names in sorted(report["profiles"].items()) if names]
    w("profiles: " + ("; ".join(profile_list) or "none"))
    w("posture:  hint %s — %s" % (report["posture_hint"]["value"], report["posture_hint"]["reason"]))
    for problem in report["problems"]:
        w("problem:  " + problem)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- verify

KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
RC_FILES = (".bashrc", ".zshrc", ".profile", ".bash_profile")


def _split_list(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def parse_verify_args(model, args):
    opts = {"json": False, "cli": [], "profile": [], "keys": [], "expect_posture": None}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg in ("--cli", "--profile", "--keys", "--expect-posture"):
            i += 1
            if i >= len(args):
                raise AkError("%s needs a value. See: ak setup --help" % arg, EXIT_USAGE)
            value = args[i]
            if arg == "--cli":
                for name in _split_list(value):
                    if name not in model.clis:
                        raise AkError("unknown CLI '%s'. CLIs: %s" % (name, " ".join(model.cli_names())), EXIT_USAGE)
                    opts["cli"].append(name)
            elif arg == "--profile":
                cli_name, sep, names = value.partition("=")
                if not sep or cli_name not in model.clis or not names:
                    raise AkError("--profile takes CLI=@name[,@name]. CLIs: %s" % " ".join(model.cli_names()), EXIT_USAGE)
                for item in _split_list(names):
                    if not item.startswith("@"):
                        raise AkError("name the profile with @, e.g. --profile %s=@work" % cli_name, EXIT_USAGE)
                    opts["profile"].append((cli_name, profiles.normalize(item[1:])))
            elif arg == "--keys":
                for name in _split_list(value):
                    if not KEY_NAME.match(name):
                        raise AkError("--keys takes variable names (upper case letters, digits, _), not values", EXIT_USAGE)
                    opts["keys"].append(name)
            else:
                if value not in ("auto", "ask"):
                    raise AkError("--expect-posture must be auto or ask", EXIT_USAGE)
                opts["expect_posture"] = value
        else:
            raise AkError("unknown option '%s'. See: ak setup --help" % arg, EXIT_USAGE)
        i += 1
    return opts


def _installer_command(report, os_name):
    root = common.KIT_ROOT
    quiet = report["container"]["detected"] or report["ci"]
    if os_name == "windows":
        return '& "%s" -NoPath' % os.path.join(root, "install.ps1") if quiet else '& "%s"' % os.path.join(root, "install.ps1")
    return 'bash "%s"%s' % (os.path.join(root, "install.sh"), " --no-rc" if quiet else "")


def _check(cid, status, message, repair=None):
    return {"id": cid, "status": status, "message": message, "repair": repair}


def _rc_block_files(host):
    found = []
    for name in RC_FILES:
        path = os.path.join(host.home(), name)
        if ">>> agentkit >>>" in host.read_text(path):
            found.append(path)
    return found


def verify(model, env, opts, host=None):
    host = host or Host(env)
    report = collect(model, env, host)
    os_name = report["os"]
    checks = []
    inst = report["install"]
    if inst["found"]:
        checks.append(_check("install.marker", "ok", "the kit is installed at %s" % inst["path"]))
        if inst["version"] and inst["version"] != common.VERSION:
            checks.append(_check("install.version", "warn", "installed %s, this code is %s" % (inst["version"], common.VERSION),
                                 _installer_command(report, os_name)))
        else:
            checks.append(_check("install.version", "ok", "installed version %s" % (inst["version"] or "unknown")))
        if inst["on_path"]:
            checks.append(_check("path.ak", "ok", "ak is on PATH"))
        else:
            bin_dir = os.path.join(inst["path"], "bin")
            fix = ('$env:Path = "%s;" + $env:Path' % bin_dir) if os_name == "windows" else 'export PATH="%s:$PATH"' % bin_dir
            checks.append(_check("path.ak", "warn", "ak is not on PATH", fix))
    else:
        checks.append(_check("install.marker", "fail", "no kit install was found", _installer_command(report, os_name)))
    if report["python"]["ok"]:
        checks.append(_check("python.version", "ok", "python %s" % report["python"]["version"]))
    else:
        checks.append(_check("python.version", "fail", "python 3.9 or newer is required (found %s)" % report["python"]["version"]))
    ef = report["env_file"]
    if not ef["exists"]:
        checks.append(_check("envfile.exists", "warn", "the env file %s does not exist" % ef["path"], _installer_command(report, os_name)))
    else:
        checks.append(_check("envfile.exists", "ok", "the env file exists"))
        if ef["mode"] is not None and ef["mode"] not in ("600", "400"):
            checks.append(_check("envfile.mode", "fail", "the env file is mode %s and holds keys" % ef["mode"], 'chmod 600 "%s"' % ef["path"]))
        else:
            checks.append(_check("envfile.mode", "ok", "the env file is private" if ef["mode"] else "file modes do not apply here"))
    for cli_name in opts["cli"]:
        if report["clis"][cli_name]["installed"]:
            checks.append(_check("cli.%s.installed" % cli_name, "ok", "%s is on PATH" % cli_name))
        else:
            checks.append(_check("cli.%s.installed" % cli_name, "fail", "%s is not installed" % cli_name, "ak install %s" % cli_name))
    for cli_name, name in opts["profile"]:
        label = profiles.label(name)
        exists = name in report["profiles"].get(cli_name, [])
        pid = "profile.%s.%s" % (cli_name, name or "default")
        if name == "":
            checks.append(_check(pid + ".exists", "ok", "@default is the CLI's own home"))
        elif exists:
            checks.append(_check(pid + ".exists", "ok", "%s profile %s exists" % (cli_name, label)))
        else:
            checks.append(_check(pid + ".exists", "fail", "%s profile %s does not exist" % (cli_name, label),
                                 "ak profiles add %s %s" % (cli_name, label)))
        if exists or name == "":
            state = profiles.login_state(model, cli_name, name, env)
            if state is True:
                checks.append(_check(pid + ".login", "ok", "a login is present for %s %s" % (cli_name, label)))
            else:
                command = model.clis[cli_name].get("login", {}).get("command")
                fix = ("ak profiles run %s %s -- %s" % (cli_name, label, command)) if command else "ak %s %s" % (cli_name, label)
                checks.append(_check(pid + ".login", "warn", "no login found for %s %s%s" % (cli_name, label, "" if state is False else " (cannot tell from files)"), fix))
    for key in opts["keys"]:
        if env.get(key):
            checks.append(_check("keys.%s.set" % key, "ok", "%s is set" % key))
        else:
            checks.append(_check("keys.%s.set" % key, "fail", "%s is not set; add it to %s (the value never goes in a chat)" % (key, ef["path"])))
    if opts["expect_posture"]:
        raw = (env.get("AGENTKIT_PERMISSIONS") or "auto").strip().lower()
        raw = raw if raw in ("ask", "auto") else "invalid"
        if raw == opts["expect_posture"]:
            checks.append(_check("posture.matches", "ok", "the posture is %s" % raw))
        else:
            line = "AGENTKIT_PERMISSIONS=%s" % opts["expect_posture"]
            if os_name == "windows":
                fix = 'Add-Content -Path "%s" -Value "%s"' % (ef["path"], line)
            else:
                fix = "printf '%%s\\n' '%s' >> \"%s\"" % (line, ef["path"])
            checks.append(_check("posture.matches", "fail", "the posture is %s, expected %s" % (raw, opts["expect_posture"]), fix))
    if inst["found"] and inst["no_rc"]:
        blocks = _rc_block_files(host)
        if blocks:
            checks.append(_check("aliases.rc", "warn", "the kit was installed with --no-rc but %s carries its block" % blocks[0], "ak alias rc --remove"))
        else:
            checks.append(_check("aliases.rc", "ok", "no shell rc carries the kit's block, as installed with --no-rc"))
    return {"schema": VERIFY_SCHEMA, "interface": common.INTERFACE, "ok": not any(c["status"] == "fail" for c in checks), "checks": checks}


def render_verify(report):
    out = []
    for c in report["checks"]:
        out.append("%-4s %-34s %s" % (c["status"], c["id"], c["message"]))
        if c["repair"]:
            out.append("     fix: %s" % c["repair"])
    out.append("verdict: %s" % ("ok" if report["ok"] else "problems found"))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ main

def main(model, args, env, host=None, stdout=None):
    stdout = stdout or sys.stdout
    if not args or args[0] in ("-h", "--help"):
        stdout.write(USAGE)
        return EXIT_OK if args else EXIT_USAGE
    verb, rest = args[0], args[1:]
    if verb == "probe":
        as_json = False
        for arg in rest:
            if arg == "--json":
                as_json = True
            else:
                raise AkError("usage: ak setup probe [--json]", EXIT_USAGE)
        report = collect(model, env, host)
        stdout.write((json.dumps(report, indent=2, sort_keys=True) + "\n") if as_json else render_probe(report))
        return EXIT_OK
    if verb == "verify":
        opts = parse_verify_args(model, rest)
        report = verify(model, env, opts, host)
        stdout.write((json.dumps(report, indent=2, sort_keys=True) + "\n") if opts["json"] else render_verify(report))
        return EXIT_OK if report["ok"] else 1
    raise AkError("unknown setup command '%s'. See: ak setup --help" % verb, EXIT_USAGE)
