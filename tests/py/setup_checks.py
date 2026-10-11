"""Bash-free checks for `ak setup` (lib/setup.py): the probe on simulated
Linux, macOS, Windows, WSL, musl and container hosts, secrecy, read-only
behaviour and the uninstalled-clone path.

    python3 tests/py/setup_checks.py            (any OS; no bash, no network)

Prints one `ok <name>` / `FAIL <name>: <why>` line per check and exits 1 when
any check failed, so the `setup` scope folds the lines in and the Windows CI
job can run it natively.
"""

import copy
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import common  # noqa: E402
import kinds  # noqa: E402
import setup  # noqa: E402
from common import AkError  # noqa: E402

FAILS = []
PLANTED_PROVIDER = "PLANTED-SETUP-KEY-3d7e0001"
PLANTED_UNRELATED = "PLANTED-UNRELATED-3d7e0002"


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


TMP = tempfile.mkdtemp(prefix="agentkit-setup-")
HOME = os.path.join(TMP, "home")
os.makedirs(HOME)
os.environ["AGENTKIT_PROFILES_DIR"] = os.path.join(TMP, "profiles")
MODEL = kinds.load()


class FakeHost(setup.Host):
    """A host whose facts the test dictates."""

    def __init__(self, env, **facts):
        setup.Host.__init__(self, env)
        self.facts = dict(os="linux", machine="x86_64", libc="glibc", musl=False, euid=1000, files={}, tools={},
                          writable=True, py=("3.12.1", True))
        self.facts.update(facts)

    def os_name(self):
        return self.facts["os"]

    def machine(self):
        return self.facts["machine"]

    def libc_family(self):
        return self.facts["libc"]

    def musl_loader(self):
        return self.facts["musl"]

    def euid(self):
        return self.facts["euid"]

    def _real(self, path):
        return path.startswith(TMP)          # files the test created; every other path is simulated

    def exists(self, path):
        return path in self.facts["files"] or (self._real(path) and os.path.exists(path))

    def read_text(self, path, limit=65536):
        if path in self.facts["files"]:
            return self.facts["files"][path]
        return setup.Host.read_text(self, path, limit) if self._real(path) else ""

    def which(self, name):
        return self.facts["tools"].get(name)

    def version_of(self, path):
        return "%s 1.0" % os.path.basename(path)

    def writable(self, path):
        return self.facts["writable"]

    def python_version(self):
        return self.facts["py"]


def env_for(extra=None):
    env = {"HOME": HOME, "USERPROFILE": HOME, "PATH": "", "ZAI_CODING_API_KEY": PLANTED_PROVIDER, "GITHUB_TOKEN": PLANTED_UNRELATED}
    env.update(extra or {})
    return env


def probe(host_facts=None, env=None):
    env = env or env_for()
    host = FakeHost(env, **(host_facts or {}))
    return setup.collect(MODEL, env, host)


def run_main(args, env=None, host=None):
    out = io.StringIO()
    try:
        code = setup.main(MODEL, args, env or env_for(), host=host, stdout=out)
    except AkError as exc:
        code = exc.code
        out.write(str(exc))
    return code, out.getvalue()


def valid(report, schema):
    path = os.path.join(TMP, "doc.json")
    with open(path, "w") as handle:
        json.dump(report, handle)
    proc = subprocess.run([sys.executable, os.path.join(HERE, "schema_check.py"), os.path.join(ROOT, "docs", "schema", schema), path],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.stdout.decode().strip()


# ------------------------------------------------------------------ probe

bare = probe({"tools": {"git": "/usr/bin/git", "bash": "/bin/bash"}})
check("setup probe: a bare Linux host is described and validates against setup-probe-v1",
      bare["os"] == "linux" and bare["arch"] == "x64" and bare["libc"] == "glibc" and valid(bare, "setup-probe-v1.json") == "valid",
      valid(bare, "setup-probe-v1.json"))
check("setup probe: schema, interface and kit version", bare["schema"] == "setup-probe-v1" and bare["interface"] == 1 and bare["version"] == common.VERSION)
check("setup probe: tools report found/version, missing ones are found false",
      bare["tools"]["git"] == {"found": True, "version": "git 1.0"} and bare["tools"]["docker"] == {"found": False, "version": None})
check("setup probe: no kit install is reported as not found", bare["install"]["found"] is False and bare["install"]["no_rc"] is None)
check("setup probe: a personal host hints ask, with the reason", bare["posture_hint"]["value"] == "ask" and "personal host" in bare["posture_hint"]["reason"])
check("setup probe: root is false for a normal user and true for euid 0",
      bare["root"] is False and probe({"euid": 0})["root"] is True)
check("setup probe: arm64 and amd64 machine names are normalised",
      probe({"machine": "aarch64"})["arch"] == "arm64" and probe({"machine": "AMD64"})["arch"] == "x64")

# containers
ctr = probe({"files": {"/.dockerenv": ""}})
check("setup probe: /.dockerenv is a container signal and the hint becomes auto",
      ctr["container"] == {"detected": True, "signals": ["dockerenv"]} and ctr["posture_hint"]["value"] == "auto", str(ctr["container"]))
check("setup probe: container variables and cgroup text are signals",
      probe({}, env_for({"container": "podman", "CODESPACES": "true"}))["container"]["signals"] == ["CODESPACES", "container"]
      and "cgroup" in probe({"files": {"/proc/1/cgroup": "0::/docker/abcdef"}})["container"]["signals"])
check("setup probe: CI is detected from a variable name only", probe({}, env_for({"GITHUB_ACTIONS": "true"}))["ci"] is True and bare["ci"] is False)
check("setup probe: a CI environment hints auto", probe({}, env_for({"CI": "1"}))["posture_hint"]["value"] == "auto")

# libc, WSL
musl = probe({"musl": True})
check("setup probe: musl is reported and listed as a problem",
      musl["libc"] == "musl" and any("musl" in p for p in musl["problems"]), str(musl["problems"]))
check("setup probe: libc is n/a off Linux", probe({"os": "macos"})["libc"] == "n/a" and probe({"os": "windows"})["libc"] == "n/a")
wsl = probe({"files": {"/proc/version": "Linux version 5.15 (microsoft-standard-WSL2)"}})
check("setup probe: WSL is detected from /proc/version and from WSL_DISTRO_NAME",
      wsl["wsl"] is True and probe({}, env_for({"WSL_DISTRO_NAME": "Ubuntu"}))["wsl"] is True and bare["wsl"] is False)

# macOS and Windows decision sets
mac = probe({"os": "macos", "machine": "arm64"})
check("setup probe: macOS is described (no libc, no WSL)", mac["os"] == "macos" and mac["arch"] == "arm64" and mac["libc"] == "n/a" and not mac["wsl"])
win_env = {k: v for k, v in env_for().items() if k != "HOME"}
win_env.update({"PSModulePath": "C:\\\\Modules", "ComSpec": "C:\\\\Windows\\\\cmd.exe"})
win = probe({"os": "windows", "euid": None}, win_env)
check("setup probe: Windows has no root notion, a PowerShell shell and no wsl/libc",
      win["os"] == "windows" and win["root"] is None and win["shell"] == "powershell" and win["libc"] == "n/a" and not win["wsl"], str(win["shell"]))
check("setup probe: the home comes from USERPROFILE when HOME is unset",
      win["env_file"]["path"].startswith(HOME), win["env_file"]["path"])
check("setup probe: cmd.exe is reported when only ComSpec is set",
      probe({"os": "windows", "euid": None}, {"USERPROFILE": HOME, "ComSpec": "cmd.exe", "PATH": ""})["shell"] == "cmd")
check("setup probe: the shell basename is taken from SHELL (also with backslashes)",
      probe({}, env_for({"SHELL": "/usr/bin/zsh"}))["shell"] == "zsh" and probe({}, env_for({"SHELL": "C:\\\\Git\\\\bin\\\\bash.exe"}))["shell"] == "bash.exe")
check("setup probe: an old python is a problem", any("python 3.9" in p for p in probe({"py": ("3.8.2", False)})["problems"]))
check("setup probe: a missing git and an unwritable home are problems",
      any("git" in p for p in bare["problems"][:0] or probe({"tools": {}})["problems"])
      and any("not writable" in p for p in probe({"writable": False})["problems"]))

# an installed kit
inst_dir = os.path.join(TMP, "agentkit")
os.makedirs(os.path.join(inst_dir, "lib"))
open(os.path.join(inst_dir, ".agentkit-install"), "w").close()
open(os.path.join(inst_dir, ".no-rc"), "w").close()
with open(os.path.join(inst_dir, "lib", "common.py"), "w") as handle:
    handle.write('VERSION = "9.9.9"\n')
inst = probe({"tools": {"ak": os.path.join(inst_dir, "bin", "ak")}}, env_for({"AGENTKIT_HOME": inst_dir}))["install"]
check("setup probe: an installed kit is found with its version, PATH state and --no-rc",
      inst == {"found": True, "path": inst_dir, "version": "9.9.9", "on_path": True, "no_rc": True}, str(inst))
check("setup probe: an install not on PATH says so",
      probe({}, env_for({"AGENTKIT_HOME": inst_dir}))["install"]["on_path"] is False)

# env file and profiles
envf = os.path.join(TMP, "envfile")
with open(envf, "w") as handle:
    handle.write("ZAI_CODING_API_KEY=%s\n" % PLANTED_PROVIDER)
os.chmod(envf, 0o644)
loose = probe({}, env_for({"AGENTKIT_ENV": envf}))
if os.name != "nt":
    check("setup probe: a group/world-readable env file is reported with its mode and as a problem",
          loose["env_file"]["mode"] == "644" and any("chmod 600" in p for p in loose["problems"]), str(loose["env_file"]))
os.makedirs(os.path.join(TMP, "profiles", "claude", "work"))
os.makedirs(os.path.join(TMP, "profiles", "codex", "2"))
prof = probe()["profiles"]
check("setup probe: profiles are listed per CLI", prof["claude"] == ["work"] and prof["codex"] == ["2"] and prof["pi"] == [], str(prof))
check("setup probe: key names are reported, never values",
      probe()["env_file"]["keys"] == ["ZAI_CODING_API_KEY"])

# secrecy and read-only
blob = json.dumps(probe()) + run_main(["probe"])[1] + run_main(["probe", "--json"])[1]
check("setup probe: no key or token value appears in text or JSON", PLANTED_PROVIDER not in blob and PLANTED_UNRELATED not in blob)


def tree(base):
    out = []
    for dirpath, _d, files in sorted(os.walk(base)):
        for name in sorted(files):
            p = os.path.join(dirpath, name)
            with open(p, "rb") as handle:
                out.append((p, hashlib.sha256(handle.read()).hexdigest(), os.stat(p).st_mtime))
    return out


before = tree(TMP)
for _ in range(3):
    probe()
    run_main(["probe"])
check("setup probe: running it changes nothing under the home or the profiles", tree(TMP) == before)

# main
code, text = run_main(["probe"])
check("setup probe: the text form exits 0 and names the sections",
      code == 0 and "system:" in text and "install:" in text and "posture:" in text, text[:200])
check("setup probe: an unknown option is a usage error (exit 2)", run_main(["probe", "--bogus"])[0] == 2)
check("setup probe: an unknown setup command is a usage error (exit 2)", run_main(["frobnicate"])[0] == 2)
check("setup probe: --help exits 0, no arguments exits 2 with the grammar",
      run_main(["--help"])[0] == 0 and run_main([])[0] == 2 and "ak setup probe" in run_main([])[1])

# an uninstalled clone: the way the skill looks at a machine first
clone_home = os.path.join(TMP, "clone-home")
os.makedirs(clone_home)
proc = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "ak.py"), "setup", "probe", "--json"], stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, env={"HOME": clone_home, "USERPROFILE": clone_home, "PATH": os.environ.get("PATH", "")})
doc = json.loads(proc.stdout.decode() or "{}")
check("setup probe: it runs from an uninstalled clone with AGENTKIT_HOME unset and validates",
      proc.returncode == 0 and doc.get("schema") == "setup-probe-v1" and doc["install"]["found"] is False and valid(doc, "setup-probe-v1.json") == "valid",
      proc.stderr.decode()[:200])
check("setup probe: ... and leaves the home empty", os.listdir(clone_home) == [])

# the probe never executes a vendor CLI: a fake `claude` that writes into HOME must not run
if os.name != "nt":
    cli_bin = os.path.join(TMP, "clibin")
    os.makedirs(cli_bin)
    marker_file = os.path.join(TMP, "cli-was-executed")
    for name in ("claude", "codex", "cursor-agent", "git"):
        path = os.path.join(cli_bin, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n: > '%s'\necho fake 1.0\n" % (marker_file if name != "git" else marker_file + ".git"))
        os.chmod(path, 0o755)
    real_env = env_for({"PATH": cli_bin + os.pathsep + os.environ.get("PATH", "")})
    report = setup.collect(MODEL, real_env)          # the real Host: it really looks at PATH
    check("setup probe: vendor CLIs on PATH are reported present without being executed",
          report["clis"]["claude"] == {"installed": True, "version": None} and report["clis"]["codex"]["installed"]
          and report["clis"]["cursor"]["installed"] and not os.path.exists(marker_file), str(report["clis"]))
    check("setup probe: only the allow-listed tools are run for a version (git yes)", report["tools"]["git"]["version"] == "fake 1.0"
          and os.path.exists(marker_file + ".git") and report["tools"]["npm"]["version"] is None)

# ----------------------------------------------------------------- verify

def verify(args, host_facts=None, env=None):
    env = env or env_for()
    host = FakeHost(env, **(host_facts or {}))
    opts = setup.parse_verify_args(MODEL, args)
    return setup.verify(MODEL, env, opts, host)


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


good_dir = os.path.join(TMP, "agentkit-good")
os.makedirs(os.path.join(good_dir, "lib"))
open(os.path.join(good_dir, ".agentkit-install"), "w").close()
with open(os.path.join(good_dir, "lib", "common.py"), "w") as handle:
    handle.write('VERSION = "%s"\n' % common.VERSION)
good_env_file = os.path.join(TMP, "good-env")
with open(good_env_file, "w") as handle:
    handle.write("ZAI_CODING_API_KEY=%s\n" % PLANTED_PROVIDER)
os.chmod(good_env_file, 0o600)
good_env = env_for({"AGENTKIT_HOME": good_dir, "AGENTKIT_ENV": good_env_file})
good_tools = {"tools": {"ak": os.path.join(good_dir, "bin", "ak"), "codex": "/usr/bin/codex", "git": "/usr/bin/git"}}

rep = verify([], good_tools, good_env)
check("setup verify: a healthy setup passes with every check ok and validates against setup-verify-v1",
      rep["ok"] and all(c["status"] == "ok" for c in rep["checks"]) and valid(rep, "setup-verify-v1.json") == "valid", str(rep["checks"]))
check("setup verify: schema and interface", rep["schema"] == "setup-verify-v1" and rep["interface"] == 1)

# every failing check names the exact repair
installer = "bash %s" % setup.quote_path(os.path.join(common.KIT_ROOT, "install.sh"), "linux")
no_kit = by_id(verify([]))
check("setup verify: no install fails with the installer command", no_kit["install.marker"]["status"] == "fail"
      and no_kit["install.marker"]["repair"] == installer, str(no_kit["install.marker"]))
in_container = by_id(verify([], {"files": {"/.dockerenv": ""}}))
check("setup verify: in a container the installer command carries --no-rc", in_container["install.marker"]["repair"] == installer + " --no-rc")
win_fix = by_id(verify([], {"os": "windows", "euid": None, "files": {"/.dockerenv": ""}}, {"USERPROFILE": HOME, "PATH": ""}))
check("setup verify: on Windows the installer command is PowerShell (-NoPath in a container)",
      win_fix["install.marker"]["repair"] == "& '%s' -NoPath" % os.path.join(common.KIT_ROOT, "install.ps1"), str(win_fix["install.marker"]))
old_inst = by_id(verify([], {"tools": {"ak": "/x/ak"}}, env_for({"AGENTKIT_HOME": inst_dir})))
check("setup verify: an install older than this code warns with the installer command",
      old_inst["install.version"]["status"] == "warn" and old_inst["install.version"]["repair"] == installer, str(old_inst["install.version"]))
off_path = by_id(verify([], {}, env_for({"AGENTKIT_HOME": good_dir})))
check("setup verify: an install not on PATH warns with the export command",
      off_path["path.ak"]["status"] == "warn" and off_path["path.ak"]["repair"] == 'export PATH=%s:"$PATH"' % setup.quote_path(os.path.join(good_dir, "bin"), "linux"), str(off_path["path.ak"]))
win_path = by_id(verify([], {"os": "windows", "euid": None}, {"USERPROFILE": HOME, "AGENTKIT_HOME": good_dir, "PATH": ""}))
check("setup verify: the Windows PATH repair is a PowerShell line",
      win_path["path.ak"]["repair"] == "$env:Path = '%s;' + $env:Path" % os.path.join(good_dir, "bin"), str(win_path["path.ak"]))
old_py = by_id(verify([], {"py": ("3.8.0", False)}))
check("setup verify: an old python fails and only the person can act (no repair command)",
      old_py["python.version"]["status"] == "fail" and old_py["python.version"]["repair"] is None)
check("setup verify: a missing env file warns with the installer command",
      by_id(verify([], {}, env_for({"AGENTKIT_ENV": os.path.join(TMP, "nope")})))["envfile.exists"]["repair"] == installer)
if os.name != "nt":
    open_env = os.path.join(TMP, "open-env")
    open(open_env, "w").close()
    os.chmod(open_env, 0o644)
    loose_chk = by_id(verify([], {}, env_for({"AGENTKIT_ENV": open_env})))["envfile.mode"]
    check("setup verify: an open env file fails with chmod 600", loose_chk["status"] == "fail" and loose_chk["repair"] == "chmod 600 %s" % setup.quote_path(open_env, "linux"), str(loose_chk))
missing_cli = by_id(verify(["--cli", "codex,pi"], good_tools, good_env))
check("setup verify: a wanted CLI that is missing fails with ak install; a present one is ok",
      missing_cli["cli.pi.installed"]["status"] == "fail" and missing_cli["cli.pi.installed"]["repair"] == "ak install pi"
      and missing_cli["cli.codex.installed"]["status"] == "ok")
os.makedirs(os.path.join(TMP, "profiles", "codex", "ok", ), exist_ok=True)
prof_chk = by_id(verify(["--profile", "claude=@absent", "--profile", "codex=@ok,@2"], good_tools, good_env))
check("setup verify: a missing profile fails with ak profiles add",
      prof_chk["profile.claude.absent.exists"]["status"] == "fail" and prof_chk["profile.claude.absent.exists"]["repair"] == "ak profiles add claude @absent")
check("setup verify: an existing profile without a login warns with the profile's login command",
      prof_chk["profile.codex.2.exists"]["status"] == "ok" and prof_chk["profile.codex.2.login"]["status"] == "warn"
      and prof_chk["profile.codex.2.login"]["repair"] == "ak profiles run codex @2 -- codex login", str(prof_chk["profile.codex.2.login"]))
os.makedirs(os.path.join(TMP, "profiles", "claude", "nologin"), exist_ok=True)
claude_login = by_id(verify(["--profile", "claude=@nologin"], good_tools, good_env))["profile.claude.nologin.login"]
check("setup verify: a CLI without a login command falls back to launching the profile", claude_login["repair"] == "ak claude @nologin", str(claude_login))
keys_chk = by_id(verify(["--keys", "ZAI_CODING_API_KEY,XAI_API_KEY"], good_tools, good_env))
check("setup verify: a key that is set is ok and one that is not fails, by name only",
      keys_chk["keys.ZAI_CODING_API_KEY.set"]["status"] == "ok" and keys_chk["keys.XAI_API_KEY.set"]["status"] == "fail"
      and good_env_file in keys_chk["keys.XAI_API_KEY.set"]["message"])
post = by_id(verify(["--expect-posture", "ask"], good_tools, good_env))["posture.matches"]
check("setup verify: a posture mismatch fails with the line to add to the env file",
      post["status"] == "fail" and post["repair"] == "printf '%%s\\n' 'AGENTKIT_PERMISSIONS=ask' >> %s" % setup.quote_path(good_env_file, "linux"), str(post))
check("setup verify: a matching posture is ok",
      by_id(verify(["--expect-posture", "ask"], good_tools, env_for({"AGENTKIT_HOME": good_dir, "AGENTKIT_ENV": good_env_file, "AGENTKIT_PERMISSIONS": "ask"})))["posture.matches"]["status"] == "ok"
      and by_id(verify(["--expect-posture", "auto"], good_tools, good_env))["posture.matches"]["status"] == "ok")
rc_home = os.path.join(TMP, "rc-home")
os.makedirs(rc_home)
with open(os.path.join(rc_home, ".bashrc"), "w") as handle:
    handle.write("# >>> agentkit >>>\n# <<< agentkit <<<\n")
rc_chk = by_id(verify([], good_tools, dict(good_env, HOME=rc_home, USERPROFILE=rc_home)))
check("setup verify: the rc consistency check applies only to installs made with --no-rc",
      "aliases.rc" not in by_id(verify([], good_tools, dict(good_env, HOME=rc_home, USERPROFILE=rc_home))))
open(os.path.join(good_dir, ".no-rc"), "w").close()
rc_chk = by_id(verify([], good_tools, dict(good_env, HOME=rc_home, USERPROFILE=rc_home)))
check("setup verify: ... only when the kit was installed with --no-rc",
      rc_chk["aliases.rc"]["status"] == "warn" and rc_chk["aliases.rc"]["repair"] == "ak alias rc --remove", str(rc_chk.get("aliases.rc")))
check("setup verify: a clean --no-rc install passes the rc check", by_id(verify([], good_tools, good_env))["aliases.rc"]["status"] == "ok")

# exit codes and arguments
fh = FakeHost(good_env, **good_tools)
check("setup verify: exit 0 when no check fails (warnings do not fail) and 1 otherwise",
      run_main(["verify"], good_env, fh)[0] == 0 and run_main(["verify", "--cli", "pi"], good_env, fh)[0] == 1)
check("setup verify: --json prints exactly one JSON object", json.loads(run_main(["verify", "--json"], good_env, fh)[1])["schema"] == "setup-verify-v1")
check("setup verify: the text form prints a fix line for a failing check and a verdict",
      "fix: ak install pi" in run_main(["verify", "--cli", "pi"], good_env, fh)[1] and "verdict:" in run_main(["verify"], good_env, fh)[1])
for label, args in (("an unknown CLI", ["verify", "--cli", "nope"]), ("a bad --profile", ["verify", "--profile", "claude"]),
                    ("a profile without @", ["verify", "--profile", "claude=work"]), ("a key that looks like a value", ["verify", "--keys", "not-a-name"]),
                    ("a bad posture", ["verify", "--expect-posture", "maybe"]), ("a missing value", ["verify", "--cli"]),
                    ("an unknown option", ["verify", "--bogus"])):
    check("setup verify: %s is a usage error (exit 2)" % label, run_main(args, good_env, fh)[0] == 2)

# secrecy and read-only
blob = json.dumps(verify(["--keys", "ZAI_CODING_API_KEY", "--expect-posture", "ask"], good_tools, good_env)) + run_main(["verify", "--keys", "ZAI_CODING_API_KEY"], good_env, fh)[1]
check("setup verify: no key or token value appears in any verify output", PLANTED_PROVIDER not in blob and PLANTED_UNRELATED not in blob)
before = tree(TMP)
for _ in range(3):
    verify(["--cli", "pi", "--keys", "XAI_API_KEY", "--expect-posture", "ask"], good_tools, good_env)
check("setup verify: running it applies no repair and changes nothing", tree(TMP) == before)

# ----------------------------------------------------------------- docker

REF, DIGEST = "v0.3.0", "8c163a81fa31151cd577797f07cfbe3e61dad49ff691de0b6d5de0975f1cc8ca"
BASE_ARGS = ["--ref", REF, "--sha256", DIGEST]


def docker(extra=None, env=None):
    return run_main(["docker"] + BASE_ARGS + (extra or []), env or env_for())


rules_ok = {}
for fmt in setup.FORMATS:
    code, text = docker(["--format", fmt, "--cli", "claude,codex"])
    rules_ok[fmt] = (code, text, setup.recipe_problems(text, fmt))
check("setup docker: every format renders and passes the static recipe rules",
      all(code == 0 and not problems for code, _t, problems in rules_ok.values()), str({f: v[2] for f, v in rules_ok.items()}))
check("setup docker: renders are deterministic", all(docker(["--format", f, "--cli", "claude,codex"])[1] == rules_ok[f][1] for f in setup.FORMATS))
dockerfile = rules_ok["dockerfile"][1]
check("setup docker: the Dockerfile pins the base by tag, the kit by tag and sha256, and installs --no-rc",
      "FROM debian:12-slim" in dockerfile and "ARG AGENTKIT_REF=%s" % REF in dockerfile and "ARG AGENTKIT_SHA256=%s" % DIGEST in dockerfile
      and "install.sh --no-rc" in dockerfile)
check("setup docker: the digest is verified before tar runs", dockerfile.index("sha256sum -c") < dockerfile.index("tar -xzf"))
check("setup docker: the kit is installed as a non-root user", dockerfile.index("USER ${AGENT_USER}") < dockerfile.index("install.sh") and "USER root" not in dockerfile)
check("setup docker: config and profiles are volumes, PATH is set, a doctor healthcheck exists",
      "VOLUME" in dockerfile and ".config/agentkit" in dockerfile and "profiles" in dockerfile and "ENV PATH=" in dockerfile and "HEALTHCHECK" in dockerfile and "ak doctor --json" in dockerfile)
check("setup docker: requested CLIs are installed with ak install (npm ones add node)",
      "RUN ak install claude codex" in dockerfile and "nodejs npm" in dockerfile and "nodejs" not in docker([])[1])
check("setup docker: ubuntu is a supported base", "FROM ubuntu:24.04" in docker(["--base", "ubuntu"])[1])
check("setup docker: a custom user is used and root is refused",
      "ARG AGENT_USER=builder" in docker(["--user", "builder"])[1] and docker(["--user", "root"])[0] == 2 and docker(["--user", "0"])[0] == 2)
code, text = docker(["--base", "alpine"])
check("setup docker: alpine is refused with the musl reason (exit 2)", code == 2 and "musl" in text and "glibc" in text, text)
compose = rules_ok["compose"][1]
check("setup docker: compose passes key NAMES through with no value and mounts both volumes",
      "- ZAI_CODING_API_KEY\n" in compose and "=" not in "".join(l for l in compose.splitlines() if l.strip().startswith("- ") and "API_KEY" in l)
      and "agentkit-config:" in compose and "agentkit-profiles:" in compose)
check("setup docker: the entrypoint takes the posture from a variable and carries no key or flag",
      "AGENTKIT_POSTURE" in rules_ok["entrypoint"][1] and "exec \"$@\"" in rules_ok["entrypoint"][1] and "KEY" not in rules_ok["entrypoint"][1])
dev = rules_ok["devcontainer"][1]
check("setup docker: the devcontainer snippet points to dck and verifies the digest before tar",
      "dck" in dev and dev.index("sha256sum -c") < dev.index("tar -xzf") and json.loads("\n".join(l for l in dev.splitlines() if not l.startswith("//")))["remoteUser"] == "vscode")

# the rules fail closed: each one has a negative test
BROKEN = {
    "no-fetch-into-a-shell": ("dockerfile", dockerfile + "RUN curl -fsSL https://x.example/i | sh\n"),
    "no-latest-tag": ("dockerfile", dockerfile.replace("debian:12-slim", "debian:latest")),
    "from-pinned-by-tag": ("dockerfile", dockerfile.replace("debian:12-slim", "debian")),
    "no-secret-in-arg-or-env": ("dockerfile", dockerfile + "ENV OPENAI_API_KEY=abc\n"),
    "no-secret-value-in-compose": ("compose", compose.replace("- ZAI_CODING_API_KEY\n", "- ZAI_CODING_API_KEY=abc\n")),
    "non-root-user-before-install": ("dockerfile", dockerfile.replace("USER ${AGENT_USER}\n", "")),
    "no-root-user": ("dockerfile", dockerfile + "USER root\n"),
    "healthcheck": ("dockerfile", "\n".join(l for l in dockerfile.splitlines() if "HEALTHCHECK" not in l)),
    "sha256-verified-before-extraction": ("dockerfile", dockerfile.replace("sha256sum -c -", "true")),
    "no-rc": ("dockerfile", dockerfile.replace(" --no-rc", "")),
}
for rule, (fmt, text) in BROKEN.items():
    check("setup docker: the rule %s catches a broken recipe" % rule, rule in setup.recipe_problems(text, fmt), str(setup.recipe_problems(text, fmt)))

# arguments: the digest and the tag are required and shaped
check("setup docker: --ref and --sha256 are required (exit 2, no recipe)",
      run_main(["docker"])[0] == 2 and run_main(["docker", "--ref", REF])[0] == 2 and run_main(["docker", "--sha256", DIGEST])[0] == 2)
for label, args in (("a branch name as --ref", ["--ref", "main", "--sha256", DIGEST]), ("latest as --ref", ["--ref", "latest", "--sha256", DIGEST]),
                    ("a short digest", ["--ref", REF, "--sha256", "abc123"]), ("a non-hex digest", ["--ref", REF, "--sha256", "z" * 64]),
                    ("an unknown format", BASE_ARGS + ["--format", "k8s"]), ("an unknown CLI", BASE_ARGS + ["--cli", "nope"]),
                    ("an unknown option", BASE_ARGS + ["--bogus", "1"]), ("a missing value", BASE_ARGS + ["--out"])):
    check("setup docker: %s is a usage error (exit 2)" % label, run_main(["docker"] + args)[0] == 2)

# secrecy: no environment value can reach a render
blob = "".join(docker(["--format", f, "--cli", "claude,codex"])[1] for f in setup.FORMATS)
check("setup docker: no key or token value reaches any render", PLANTED_PROVIDER not in blob and PLANTED_UNRELATED not in blob)

# --out: a new file, mode 644, never overwriting; stdout otherwise
out_file = os.path.join(TMP, "Dockerfile.out")
code, _t = docker(["--out", out_file])
check("setup docker: --out writes a new file with the render", code == 0 and open(out_file).read() == docker([])[1])
if os.name != "nt":
    check("setup docker: --out creates mode 644", oct(os.stat(out_file).st_mode & 0o777) == "0o644")
before_text = open(out_file).read()
code, text = docker(["--out", out_file, "--format", "compose"])
check("setup docker: --out never overwrites an existing file (exit 2, content kept)", code == 2 and "never overwrites" in text and open(out_file).read() == before_text)
check("setup docker: a directory that cannot be written is a usage error, not a crash",
      docker(["--out", os.path.join(TMP, "no-such-dir", "x")])[0] == 2)

# the version probe's child never receives a key or token variable
if os.name != "nt":
    env_bin = os.path.join(TMP, "envbin")
    os.makedirs(env_bin)
    env_marker = os.path.join(TMP, "env-seen")
    script = os.path.join(env_bin, "git")
    with open(script, "w") as handle:
        handle.write("#!/bin/sh\nprintf '%%s|%%s|%%s' \"${ZAI_CODING_API_KEY:-unset}\" \"${GITHUB_TOKEN:-unset}\" \"${HARMLESS:-unset}\" > '%s'\necho git 1.0\n" % env_marker)
    os.chmod(script, 0o755)
    child_env = env_for({"PATH": env_bin + os.pathsep + os.environ.get("PATH", ""), "HARMLESS": "visible"})
    setup.collect(MODEL, child_env)
    seen = open(env_marker).read() if os.path.exists(env_marker) else "never ran"
    check("setup probe: a tool run for its version never sees a key or token variable (other variables pass)",
          seen == "unset|unset|visible", seen)

# review hardening: repair commands are built from environment paths and must not be injectable
# (POSIX only: Windows forbids '"' in a file name, and the repair there is PowerShell, checked below)
if os.name != "nt":
    evil = os.path.join(TMP, 'we"ird $(touch pwned) `id` ; dir')
    os.makedirs(evil, exist_ok=True)
    evil_env = os.path.join(evil, "env")
    open(evil_env, "w").close()
    os.chmod(evil_env, 0o644)
    cmd = by_id(verify([], {}, env_for({"AGENTKIT_ENV": evil_env})))["envfile.mode"]["repair"]
    check("setup review: a path with quotes, $(), backticks and ; is one shell word in the repair command",
          shlex.split(cmd) == ["chmod", "600", evil_env], cmd)
    check("setup review: ... and running the repair changes the mode without executing the path",
          subprocess.run(["sh", "-c", cmd], cwd=TMP).returncode == 0 and oct(os.stat(evil_env).st_mode & 0o777) == "0o600"
          and not os.path.exists(os.path.join(TMP, "pwned")))
check("setup review: PowerShell paths are single-quoted with doubled quotes", setup.quote_path("C:\\it's here\\env", "windows") == "'C:\\it''s here\\env'")
hostile = probe({"tools": {"git": "/usr/bin/git"}}, env_for({"SHELL": "/bin/ba\x1b[31msh\x07"}))
check("setup review: control characters from SHELL or a tool's version never reach the report",
      hostile["shell"] == "ba[31msh" and "\x1b" not in json.dumps(hostile) and "\x07" not in json.dumps(hostile), str(hostile["shell"]))
check("setup review: printable caps and cleans", setup.printable("a\x1bb" + "c" * 200, 10) == "abcccccccc")

# static portability rule
import re  # noqa: E402
source = open(os.path.join(ROOT, "lib", "setup.py"), encoding="utf-8").read()
banned = re.findall(r"import (?:fcntl|pwd|grp|termios|resource)\b|os\.fork|signal\.alarm|os\.getuid\b|/home/|C:\\\\", source)
check("setup platform: lib/setup.py has no POSIX-only import or hardcoded path", not banned, str(banned))

if FAILS:
    sys.exit(1)
