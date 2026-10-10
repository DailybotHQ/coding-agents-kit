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

# static portability rule
import re  # noqa: E402
source = open(os.path.join(ROOT, "lib", "setup.py"), encoding="utf-8").read()
banned = re.findall(r"import (?:fcntl|pwd|grp|termios|resource)\b|os\.fork|signal\.alarm|os\.getuid\b|/home/|C:\\\\", source)
check("setup platform: lib/setup.py has no POSIX-only import or hardcoded path", not banned, str(banned))

if FAILS:
    sys.exit(1)
