"""`ak install [<cli>…] [--all] [--allow-unverified]` — install missing CLIs, pinned and verified.

Each CLI's channel, exact version and digests are data
(providers.toml [clis.<cli>.install]). Nothing downloaded is run or
installed before its digest matches:

  binary   one executable per platform, checked against its sha256, then
           installed as ~/.local/bin/<executable>;
  tarball  one archive per platform, checked against its sha256, unpacked
           safely into a versioned directory, then linked into ~/.local/bin;
  npm      the registry tarball of <package>@<version>, checked against the
           pinned `integrity` (sha512), then `npm install -g <that file>`.

A platform with no pinned digest is refused. A CLI that cannot be pinned
carries `unverified = "<reason>"` and installs only with
--allow-unverified. Vendor install scripts are never run.

Already-installed CLIs are skipped: nothing is upgraded, moved or removed.
One failing install never stops the others. Without a CLI name it only
reports what is missing and how it would be installed.
"""

import base64
import hashlib
import os
import platform as platform_mod
import shutil
import subprocess
import tarfile
import tempfile

import common
import kinds as kinds_mod
from common import AkError, EXIT_USAGE

NODE_HINTS = {
    "macos": "brew install node   (https://nodejs.org)",
    "linux": "your distribution's nodejs + npm packages, or https://nodejs.org",
    "windows": "winget install OpenJS.NodeJS.LTS   (https://nodejs.org)",
}
NPM_REGISTRY = "https://registry.npmjs.org"
USAGE = "usage: ak install [<cli>…] [--all] [--allow-unverified]"


def platform_key():
    """<os>-<arch> as providers.toml spells it: linux|macos|windows - x64|arm64."""
    machine = platform_mod.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return "%s-%s" % (common.os_name(), arch)


def bin_dir():
    return os.path.join(common.home(), ".local", "bin")


def _expand(text, inst, plat_token=""):
    return text.replace("{version}", inst.get("version", "")).replace("{platform}", plat_token)


def npm_tarball_url(inst):
    package = inst["package"]
    base = package.rsplit("/", 1)[-1]
    return "%s/%s/-/%s-%s.tgz" % (NPM_REGISTRY, package, base, inst["version"])


def plan_line(model, cli_name, plat=None):
    inst = model.clis[cli_name]["install"]
    plat = plat or platform_key()
    channel = inst["channel"]
    if channel == "npm":
        extra = " ".join(inst.get("npm_args", []))
        how = "verify %s@%s against its pinned integrity, then npm install -g %s<tarball>" % (
            inst["package"], inst["version"], extra + " " if extra else "")
    else:
        token = inst.get("platforms", {}).get(plat)
        if not token:
            return "no pinned %s artifact for %s — install it from the vendor: %s" % (
                cli_name, plat, model.clis[cli_name].get("docs", ""))
        how = "download %s, verify sha256 %s…, install into %s" % (
            _expand(inst["url"], inst, token), inst.get("sha256", {}).get(plat, "?")[:12], bin_dir())
    if inst.get("unverified"):
        how += "   (unverified: %s — needs --allow-unverified)" % inst["unverified"]
    return how


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


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def integrity_of(path):
    """npm's Subresource Integrity form: sha512-<base64>."""
    digest = hashlib.sha512()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return "sha512-" + base64.b64encode(digest.digest()).decode("ascii")


def installer_env(env):
    """The environment npm sees: no key variables (npm lifecycle scripts of
    any transitive package could read them)."""
    return {k: v for k, v in env.items() if not common.secret_like(k)}


def _verify(cli_name, path, expected, actual_fn, allow_unverified, inst):
    if not expected:
        if inst.get("unverified") and allow_unverified:
            print("%s: installing UNVERIFIED (%s) — --allow-unverified was given" % (cli_name, inst["unverified"]))
            return True
        print("%s: refused — no pinned digest%s" % (
            cli_name, " (%s; pass --allow-unverified to accept)" % inst["unverified"] if inst.get("unverified") else ""))
        return False
    actual = actual_fn(path)
    if actual != expected:
        print("%s: refused — checksum mismatch (expected %s, got %s); nothing was installed"
              % (cli_name, expected, actual))
        return False
    return True


def _safe_members(archive, strip):
    """Members of a tar archive with `strip` leading components removed;
    refuses absolute paths, `..`, links leaving the tree and special files."""
    out = []
    for member in archive.getmembers():
        parts = [p for p in member.name.split("/") if p not in ("", ".")]
        if len(parts) <= strip:
            continue
        rel = parts[strip:]
        if any(p == ".." for p in rel) or member.name.startswith("/"):
            raise AkError("refusing an archive entry outside its directory: %s" % member.name)
        if member.isdev() or member.isfifo():
            raise AkError("refusing a special file in the archive: %s" % member.name)
        if member.issym() or member.islnk():
            target = member.linkname
            if target.startswith("/") or ".." in target.split("/"):
                raise AkError("refusing a link that leaves the archive: %s -> %s" % (member.name, target))
            if member.islnk():
                link_parts = [p for p in target.split("/") if p not in ("", ".")]
                if len(link_parts) <= strip:
                    raise AkError("refusing a hard link outside the archive: %s" % member.name)
                member.linkname = "/".join(link_parts[strip:])
        member.name = "/".join(rel)
        out.append(member)
    return out


def _link(cli_name, target, name, owned_root):
    """Link ~/.local/bin/<name> -> target. Only a missing path or a symlink
    that already points into `owned_root` (an earlier install of this CLI)
    is replaced; anything else is left alone and reported."""
    os.makedirs(bin_dir(), exist_ok=True)
    link = os.path.join(bin_dir(), name)
    if os.path.lexists(link):
        current = os.path.realpath(link) if os.path.islink(link) else None
        root = os.path.realpath(owned_root)
        if current is None or not (current == root or current.startswith(root + os.sep)):
            print("%s: left %s alone (it is not a link this kit made); run %s directly"
                  % (cli_name, link, target))
            return
        os.remove(link)
    os.symlink(target, link)


def _install_binary(cli_name, cli, inst, plat, tmpdir, env, allow_unverified):
    token = inst.get("platforms", {}).get(plat)
    if not token:
        print("%s: refused — no pinned artifact for %s; install it from the vendor: %s"
              % (cli_name, plat, cli.get("docs", "")))
        return False
    url = _expand(inst["url"], inst, token)
    tmp = os.path.join(tmpdir, "artifact")
    if not _download(url, tmp, env):
        print("%s: download failed: %s" % (cli_name, url))
        return False
    if not _verify(cli_name, tmp, inst.get("sha256", {}).get(plat), sha256_of, allow_unverified, inst):
        return False
    if inst["channel"] == "binary":
        os.makedirs(bin_dir(), exist_ok=True)
        dest = os.path.join(bin_dir(), cli["executable"])
        staged = dest + ".agentkit-new"
        shutil.copyfile(tmp, staged)
        os.chmod(staged, 0o755)
        os.replace(staged, dest)
        return True
    into = os.path.join(common.home(), _expand(inst["into"], inst).replace("~/", "", 1))
    staging = into + ".agentkit-new"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        _extract(tmp, staging, inst)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    previous = into + ".agentkit-old"
    shutil.rmtree(previous, ignore_errors=True)
    if os.path.isdir(into):
        os.replace(into, previous)
    try:
        os.replace(staging, into)
    except OSError:
        if os.path.isdir(previous) and not os.path.exists(into):
            os.replace(previous, into)   # put the previous version back
        raise
    shutil.rmtree(previous, ignore_errors=True)
    owned = os.path.dirname(into)
    for name, rel in sorted(inst.get("links", {}).items()):
        _link(cli_name, os.path.join(into, rel), name, owned)
    return True


def _extract(tmp, staging, inst):
    with tarfile.open(tmp, "r:*") as archive:
        members = _safe_members(archive, int(inst.get("strip", 0)))
        if hasattr(tarfile, "data_filter"):  # python >= 3.12 (and backports): a second, stdlib check
            archive.extractall(staging, members=members, filter="data")
        else:
            archive.extractall(staging, members=members)


def _install_npm(cli_name, inst, tmpdir, env, allow_unverified):
    npm = common.which("npm", env)
    if not npm:
        print("%s: npm is not installed — install Node first: %s" % (cli_name, NODE_HINTS.get(common.os_name(),
                                                                                              "https://nodejs.org")))
        return False
    url = npm_tarball_url(inst)
    tgz = os.path.join(tmpdir, "%s-%s.tgz" % (inst["package"].rsplit("/", 1)[-1], inst["version"]))
    if not _download(url, tgz, env):
        print("%s: download failed: %s" % (cli_name, url))
        return False
    if not _verify(cli_name, tgz, inst.get("integrity"), integrity_of, allow_unverified, inst):
        return False
    argv = [npm, "install", "-g"] + list(inst.get("npm_args", [])) + [tgz]
    return subprocess.call(argv, env=env) == 0


def install_one(model, cli_name, env, allow_unverified=False, plat=None):
    """True when installed (or already present)."""
    env = installer_env(env)
    cli = model.clis[cli_name]
    exe = common.resolve_executable(cli, env)
    if exe:
        print("%s: already installed — skip (%s)" % (cli_name, exe))
        return True
    inst = cli["install"]
    plat = plat or platform_key()
    print("%s: installing %s — %s" % (cli_name, inst["version"], plan_line(model, cli_name, plat)))
    tmpdir = tempfile.mkdtemp(prefix="agentkit-install-")
    try:
        if inst["channel"] == "npm":
            ok = _install_npm(cli_name, inst, tmpdir, env, allow_unverified)
        else:
            ok = _install_binary(cli_name, cli, inst, plat, tmpdir, env, allow_unverified)
    except (AkError, tarfile.TarError, OSError) as exc:
        print("%s: refused — %s" % (cli_name, exc))
        ok = False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        print("%s: not installed — see %s" % (cli_name, cli.get("docs", "the vendor's docs")))
        return False
    print("%s: installed%s" % (cli_name, "" if common.resolve_executable(cli, env) else
                               " (add %s to PATH, or open a new shell)" % bin_dir()))
    return True


def main(model, args, env):
    install_all = "--all" in args
    allow_unverified = "--allow-unverified" in args
    names = [a for a in args if a not in ("--all", "--allow-unverified")]
    for a in names:
        if a.startswith("-"):
            raise AkError(USAGE, EXIT_USAGE)
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
    failed = [c for c in clis if not install_one(model, c, env, allow_unverified)]
    if failed:
        common.warn("not installed: %s" % " ".join(failed))
        return 1
    return 0
