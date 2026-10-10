"""Executable documentation for the agentkit-setup skill.

A skill that teaches commands nobody has run is a liability, so the commands
of its flows are extracted from the markdown and run, in order, in sandboxes
that simulate a fresh host, a host that already has the kit, a container
recipe and a broken install. A drift between the words and the tool (a
renamed flag, a changed repair) fails the suite.

    python3 tests/py/skill_scenarios.py <kit-root> [--skill-dir DIR]

A fenced block whose first line is `# test: <scenario>` is run; the scenario
names group blocks into flows (see FLOWS). Everything else must be marked
non-runnable offline (it needs the network, a package manager, Docker, or
Windows). The sandbox has a fake `git` that "clones" this checkout (and
refuses any tag, URL or branch the skill should not use), the real python
and bash, and no network. Prints `ok <name>` / `FAIL <name>: <why>`.
POSIX only (the blocks are bash); the Windows flow is covered natively in CI.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.abspath(sys.argv[1])
SKILL_DIR = os.path.join(ROOT, "skills", "agentkit-setup")
if "--skill-dir" in sys.argv:
    SKILL_DIR = os.path.abspath(sys.argv[sys.argv.index("--skill-dir") + 1])

sys.path.insert(0, os.path.join(ROOT, "lib"))
import common  # noqa: E402
import setup  # noqa: E402
import kinds  # noqa: E402

MODEL = kinds.load()
PLANTED = "planted-e2e-key-0x1"
FAILS = []
PREFIX = "setup-skill scenario: "
TAG = "v%s" % common.VERSION
REPO_URL = "https://github.com/DailybotHQ/coding-agents-kit"

FAKE_GIT = r'''#!/usr/bin/env python3
"""A fake git: `git clone --branch vX.Y.Z <url>` copies the checkout it was built from."""
import os, shutil, sys
args = sys.argv[1:]
if args[:1] == ["clone"]:
    rest = args[1:]
    tag = url = None
    while rest:
        if rest[0] == "--branch":
            tag = rest[1]; rest = rest[2:]
        else:
            url = rest[0]; rest = rest[1:]
    if tag != os.environ["FAKE_GIT_TAG"] or url != os.environ["FAKE_GIT_URL"]:
        sys.stderr.write("fake git: refusing clone of %r at %r\n" % (url, tag)); sys.exit(128)
    dest = os.path.join(os.getcwd(), url.rstrip("/").rsplit("/", 1)[-1])
    shutil.rmtree(dest, ignore_errors=True)
    src = os.environ["FAKE_GIT_SRC"]
    os.makedirs(dest)
    for name in ("bin", "lib", "providers.toml", "skills", "docs", "LICENSE", "README.md", "CREDITS.md", "CHANGELOG.md", "install.sh"):
        p = os.path.join(src, name)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(dest, name), ignore=shutil.ignore_patterns("__pycache__"))
        elif os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, name))
    sys.exit(0)
sys.exit(0)
'''


def check(name, cond, why=""):
    if cond:
        print("ok %s%s" % (PREFIX, name))
    else:
        FAILS.append(name)
        print("FAIL %s%s: %s" % (PREFIX, name, why or "condition false"))


def read_docs():
    files = [os.path.join(SKILL_DIR, "SKILL.md")]
    refs = os.path.join(SKILL_DIR, "references")
    files += [os.path.join(refs, n) for n in sorted(os.listdir(refs))]
    return [(f, open(f, encoding="utf-8").read()) for f in files]


def blocks(docs):
    """(file, language, lines) for every fenced block."""
    out = []
    for path, text in docs:
        for lang, body in re.findall(r"```(\w*)\n(.*?)```", text, re.S):
            out.append((os.path.basename(path), lang, textwrap.dedent(body).rstrip().splitlines()))
    return out


def scenario_lines(docs):
    """scenario -> ordered list of command lines (the `# test:` marker removed)."""
    found = {}
    for _file, _lang, lines in blocks(docs):
        if lines and re.match(r"#\s*test:\s*(\S+)", lines[0]):
            name = re.match(r"#\s*test:\s*(\S+)", lines[0]).group(1)
            found.setdefault(name, []).extend(l for l in lines[1:] if l.strip() and not l.strip().startswith("#"))
    return found


class Sandbox(object):
    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="agentkit-e2e-")
        self.home = os.path.join(self.base, "home")
        self.work = os.path.join(self.base, "work")
        self.bin = os.path.join(self.base, "bin")
        for d in (self.home, self.work, self.bin):
            os.makedirs(d)
        with open(os.path.join(self.bin, "git"), "w") as handle:
            handle.write(FAKE_GIT)
        os.chmod(os.path.join(self.bin, "git"), 0o755)
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        self.extra_path = []
        self.log = []

    def env(self):
        path = os.pathsep.join([self.bin] + self.extra_path + ["/usr/bin", "/bin"])
        return {"HOME": self.home, "PATH": path, "FAKE_GIT_TAG": TAG, "FAKE_GIT_URL": REPO_URL, "FAKE_GIT_SRC": ROOT,
                "ZAI_CODING_API_KEY": PLANTED, "LC_ALL": "C"}

    def run(self, line):
        proc = subprocess.run(["bash", "-c", line], cwd=self.work, env=self.env(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        out = proc.stdout.decode("utf-8", "replace")
        self.log.append((line, proc.returncode, out))
        return proc.returncode, out

    def tree(self):
        state = []
        for dirpath, _d, files in sorted(os.walk(self.home)):
            for name in sorted(files):
                p = os.path.join(dirpath, name)
                if os.path.islink(p):
                    continue
                with open(p, "rb") as handle:
                    state.append((os.path.relpath(p, self.home), hashlib.sha256(handle.read()).hexdigest()))
        return state

    def output(self):
        return "".join(entry[2] for entry in self.log)


def allowed(line, scenario):
    """Exit codes accepted for a documented line: a verify verdict may be 0 or 1."""
    return (0, 1) if re.search(r"setup verify\b", line) else (0,)


def run_flow(sandbox, docs_lines, scenarios):
    failures = []
    for scenario in scenarios:
        for line in docs_lines.get(scenario, []):
            code, out = sandbox.run(line)
            if code not in allowed(line, scenario):
                failures.append("%s: `%s` exited %d: %s" % (scenario, line[:90], code, out.strip()[-160:]))
                return failures
            if scenario == "install":
                installed_bin = os.path.join(sandbox.home, ".local", "share", "agentkit", "bin")
                if installed_bin not in sandbox.extra_path:
                    sandbox.extra_path.append(installed_bin)      # what the person does after a --no-rc install
    return failures


def main():
    docs = read_docs()
    lines = scenario_lines(docs)
    needed = ("probe", "install", "verify", "container")
    check("the skill marks runnable blocks for the flows (%s)" % ", ".join(needed), all(n in lines for n in needed), str(sorted(lines)))
    if not all(n in lines for n in needed):
        return 1

    # ---- 1. fresh host: probe -> install -> verify
    fresh = Sandbox()
    failures = run_flow(fresh, lines, ["probe", "install", "verify"])
    check("fresh host: probe, install and verify run as written", not failures, "; ".join(failures))
    probe_json = None
    for line, code, out in fresh.log:
        if "setup probe" in line and code == 0:
            try:
                probe_json = json.loads(out[out.index("{"):])
            except ValueError:
                pass
    check("fresh host: the first command's JSON is a setup-probe-v1 report of an uninstalled machine",
          probe_json and probe_json["schema"] == "setup-probe-v1" and probe_json["install"]["found"] is False, str(probe_json and probe_json.get("schema")))
    check("fresh host: the install left the kit in place, marked --no-rc, with a private env file",
          os.path.isfile(os.path.join(fresh.home, ".local", "share", "agentkit", ".no-rc"))
          and oct(os.stat(os.path.join(fresh.home, ".config", "agentkit", "env")).st_mode & 0o777) == "0o600")
    verify_json = None
    for line, code, out in fresh.log:
        if line.startswith("python3 coding-agents-kit/lib/ak.py setup verify --json"):
            verify_json = json.loads(out[out.index("{"):])
    check("fresh host: verify after the install reports no failing install check",
          verify_json and verify_json["schema"] == "setup-verify-v1" and not [c for c in verify_json["checks"] if c["status"] == "fail" and c["id"].startswith("install")],
          str(verify_json and [c for c in verify_json["checks"] if c["status"] == "fail"]))
    first_tree = fresh.tree()

    # ---- 2. host that already has the kit: the same flow again is a no-op
    failures = run_flow(fresh, lines, ["probe", "install", "verify"])
    check("installed host: running the flow again succeeds", not failures, "; ".join(failures))
    check("installed host: ... and changes nothing under the home (idempotent)", fresh.tree() == first_tree)

    # ---- 3. container: probe then render every taught recipe
    container = Sandbox()
    failures = run_flow(container, lines, ["probe", "container"])
    check("container: the probe and the recipe commands run as written", not failures, "; ".join(failures))
    rendered = [(line, out) for line, code, out in container.log if "setup docker" in line]
    check("container: every rendered recipe passes the static safety rules",
          rendered and all(not setup.recipe_problems(out, re.search(r"--format (\w+)", line).group(1) if "--format" in line else "dockerfile") for line, out in rendered),
          str([(l[-60:], setup.recipe_problems(o, "dockerfile")) for l, o in rendered]))
    check("container: the sandbox's home stayed empty (rendering writes nothing)", container.tree() == [])

    # ---- 4. broken install: verify names each failure and its repair; the repairs run; verify turns green
    broken = Sandbox()
    run_flow(broken, lines, ["probe", "install"])
    env_file = os.path.join(broken.home, ".config", "agentkit", "env")
    os.chmod(env_file, 0o644)
    code, out = broken.run("ak setup verify --cli claude --profile claude=@work --keys ZAI_CODING_API_KEY --json")
    report = json.loads(out[out.index("{"):])
    failing = {c["id"]: c for c in report["checks"] if c["status"] == "fail"}
    check("broken install: verify exits 1 and names the loose env file, the missing CLI and the missing profile",
          code == 1 and {"envfile.mode", "cli.claude.installed", "profile.claude.work.exists"} <= set(failing), str(sorted(failing)))
    check("broken install: every failure the person can fix with a command carries it",
          failing["envfile.mode"]["repair"] and failing["profile.claude.work.exists"]["repair"] == "ak profiles add claude @work", str(failing))
    for cid in ("envfile.mode", "profile.claude.work.exists"):
        rcode, rout = broken.run(failing[cid]["repair"])
        check("broken install: the repair for %s runs (exit 0)" % cid, rcode == 0, rout[-160:])
    code, out = broken.run("ak setup verify --profile claude=@work --keys ZAI_CODING_API_KEY --json")
    again = json.loads(out[out.index("{"):])
    check("broken install: after the repairs the checks that had a command are green",
          not [c for c in again["checks"] if c["status"] == "fail"], str([c["id"] for c in again["checks"] if c["status"] == "fail"]))

    # ---- 5. unsupported platform: musl is a documented stop, and the recipe refuses it
    code, out = container.run("python3 coding-agents-kit/lib/ak.py setup docker --ref %s --sha256 %s --base alpine" % (TAG, "0" * 64))
    check("unsupported platform: an Alpine recipe is refused with the musl reason", code == 2 and "musl" in out, out[-160:])
    skill_text = docs[0][1]
    check("unsupported platform: the skill tells the agent to stop on musl", re.search(r"`libc` is `musl`\s*\|\s*stop", skill_text) is not None)

    # ---- 6. nothing leaked, nothing outside the sandbox
    everything = fresh.output() + container.output() + broken.output()
    files = ""
    for sb in (fresh, container, broken):
        for rel, _h in sb.tree():
            with open(os.path.join(sb.home, rel), "rb") as handle:
                files += handle.read().decode("latin-1")
    check("no run printed or wrote the planted key value", PLANTED not in everything and PLANTED not in files)

    # ---- 7. every fenced command is either executed or marked as not runnable offline
    unmarked = []
    signals = ("curl", "apt-get", "brew ", "winget", "docker", "install.ps1", "py -3", "pwsh", "powershell", "ak install", "ak profiles",
               "ak alias", "dck", "SHA256SUMS", "grep coding-agents-kit", "$env:", "$HOME\\", "ak.cmd", "AGENTKIT_PERMISSIONS=ask", "--uninstall",
               "--out", "docker run")
    for filename, lang, blk in blocks(docs):
        body = "\n".join(blk)
        if blk and re.match(r"#\s*test:", blk[0]):
            continue
        if lang in ("powershell",) or any(sig in body for sig in signals):
            continue
        unmarked.append("%s: %s" % (filename, blk[0][:60] if blk else ""))
    check("every fenced command is run by a scenario or marked non-runnable offline (network, package manager, Docker, Windows)",
          not unmarked, str(unmarked))
    for sb in (fresh, container, broken):
        shutil.rmtree(sb.base, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    code = main()
    sys.exit(code)
