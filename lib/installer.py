"""`ak install [<cli>…] [--all]` — install missing CLIs from their vendors.

Each CLI's official channel and pinned version is data
(providers.toml [clis.<cli>.install]):

  script  the vendor's installer script, downloaded over HTTPS to a
          private temporary file and then run with bash — never piped
          from the network into a shell — with the pinned version as its
          argument when the vendor supports one (Claude Code does; Cursor
          and Grok do not, which the data states);
  npm     `npm install -g <package>@<version>` (exact pin).

Already-installed CLIs are skipped: nothing is upgraded, moved or removed.
One failing install never stops the others. Without a CLI name it only
reports what is missing and how it would be installed.
"""

import os
import shutil
import subprocess
import tempfile

import common
import kinds as kinds_mod
from common import AkError, EXIT_USAGE

NODE_HINTS = {
    "macos": "brew install node   (https://nodejs.org)",
    "linux": "your distribution's nodejs + npm packages, or https://nodejs.org",
    "windows": "winget install OpenJS.NodeJS.LTS   (https://nodejs.org)",
}


def plan_line(model, cli_name):
    inst = model.clis[cli_name]["install"]
    if inst["channel"] == "npm":
        extra = " ".join(inst.get("npm_args", []))
        return "npm install -g %s%s@%s" % (extra + " " if extra else "", inst["package"], inst["version"])
    version = inst.get("version") or ""
    return "download %s, then: bash <it>%s%s" % (inst["url"], " " + version if version else "",
                                                 "" if version else "   (unpinned: %s)" % inst.get("unpinned", ""))


def _download(url, dest, env):
    curl = common.which("curl", env)
    if curl:
        return subprocess.call([curl, "-fsSL", "--proto", "=https", "--tlsv1.2", "-o", dest, url], env=env) == 0
    try:  # stdlib fallback when curl is absent
        import urllib.request
        if not url.startswith("https://"):
            return False
        with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
            shutil.copyfileobj(response, out)
        return True
    except Exception:
        return False


def installer_env(env):
    """The environment a vendor installer or npm sees: no key variables
    (npm lifecycle scripts of any transitive package could read them)."""
    return {k: v for k, v in env.items() if not common.secret_like(k)}


def install_one(model, cli_name, env):
    """True when installed (or already present)."""
    env = installer_env(env)
    cli = model.clis[cli_name]
    exe = common.resolve_executable(cli, env)
    if exe:
        print("%s: already installed — skip (%s)" % (cli_name, exe))
        return True
    inst = cli["install"]
    print("%s: installing — %s" % (cli_name, plan_line(model, cli_name)))
    if inst["channel"] == "npm":
        npm = common.which("npm", env)
        if not npm:
            print("%s: npm is not installed — install Node first: %s" % (cli_name, NODE_HINTS.get(common.os_name(),
                                                                                                  "https://nodejs.org")))
            return False
        argv = [npm, "install", "-g"] + list(inst.get("npm_args", [])) + ["%s@%s" % (inst["package"], inst["version"])]
        ok = subprocess.call(argv, env=env) == 0
    else:
        bash = common.which("bash", env)
        if not bash:
            print("%s: bash is required to run the vendor installer" % cli_name)
            return False
        tmpdir = tempfile.mkdtemp(prefix="agentkit-install-")
        try:
            script = os.path.join(tmpdir, "install.sh")
            if not _download(inst["url"], script, env):
                print("%s: download failed: %s" % (cli_name, inst["url"]))
                return False
            args = [a.replace("{version}", inst.get("version", "")) for a in inst.get("args", [])]
            args = [a for a in args if a]
            ok = subprocess.call([bash, script] + args, env=env) == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        print("%s: install failed — see %s" % (cli_name, cli.get("docs", "the vendor's docs")))
        return False
    print("%s: installed%s" % (cli_name, "" if common.resolve_executable(cli, env) else
                               " (open a new shell if it is not on PATH yet)"))
    return True


def main(model, args, env):
    install_all = "--all" in args
    names = [a for a in args if a != "--all"]
    for a in names:
        if a.startswith("-"):
            raise AkError("usage: ak install [<cli>…] [--all]", EXIT_USAGE)
    try:
        clis = []
        for name in names:
            cli_name = model.cli_of(name)
            if cli_name not in clis:
                clis.append(cli_name)
    except kinds_mod.KindsError as exc:
        raise AkError(str(exc), EXIT_USAGE)
    if install_all:
        clis = model.cli_names()
    if not clis:
        print("%-9s %-10s %s" % ("CLI", "STATE", "HOW (ak install <cli> | ak install --all)"))
        for cli_name in model.cli_names():
            exe = common.resolve_executable(model.clis[cli_name], env)
            print("%-9s %-10s %s" % (cli_name, "installed" if exe else "missing",
                                     exe if exe else plan_line(model, cli_name)))
        return 0
    failed = [c for c in clis if not install_one(model, c, env)]
    if failed:
        common.warn("not installed: %s" % " ".join(failed))
        return 1
    return 0
