"""Checks for `ak install` verification (lib/installer.py), no network.

Run by tests/scopes/install.sh: python3 install_checks.py <kit-root> <scratch-dir>
Prints one `ok <name>` / `FAIL <name>: <why>` line per check.

A fixture providers.toml is the shipped one with the digests of a few
install tables replaced by the digests of local fixture artifacts; a fake
curl serves those artifacts by URL and a fake npm records its argv and the
names of key variables it sees. The real pins are never needed here.
"""

import base64
import contextlib
import hashlib
import io
import os
import shutil
import stat
import sys
import tarfile

ROOT, SCRATCH = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, "lib"))

import kinds  # noqa: E402
import installer  # noqa: E402

PLANTED = "planted-install-key-5c1e"


def check(name, cond, why=""):
    print(("ok %s" % name) if cond else ("FAIL %s: %s" % (name, why or "condition false")))


def slug(url):
    return "".join(c if c.isalnum() else "_" for c in url)


ART = os.path.join(SCRATCH, "artifacts")
BIN = os.path.join(SCRATCH, "bin")
LOG = os.path.join(SCRATCH, "npm.log")
for d in (ART, BIN):
    os.makedirs(d, exist_ok=True)

with open(os.path.join(BIN, "curl"), "w") as fh:
    fh.write("""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift ;; https://*) url="$1" ;; esac; shift; done
src="%s/$(printf '%%s' "$url" | tr -c 'A-Za-z0-9' '_')"
[ -f "$src" ] || exit 22
cp "$src" "$out"
""" % ART)
with open(os.path.join(BIN, "npm"), "w") as fh:
    fh.write("""#!/bin/sh
echo "NPM $*" >> "%s"
env | grep -E '_API_KEY|_TOKEN' | sed 's/=.*//; s/^/NPM-ENV /' >> "%s"
exit 0
""" % (LOG, LOG))
for name in ("curl", "npm"):
    os.chmod(os.path.join(BIN, name), 0o755)


def serve(url, data):
    with open(os.path.join(ART, slug(url)), "wb") as fh:
        fh.write(data)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sri(data):
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


def tarball(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data, mode in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


with open(kinds.PROVIDERS_FILE) as fh:
    text = fh.read()
real = kinds.load()
inst = {c: real.clis[c]["install"] for c in real.cli_names()}

claude_bin = b"#!/bin/sh\necho fake claude\n"
cursor_tgz = tarball([("dist-package/cursor-agent", b"#!/bin/sh\necho fake cursor\n", 0o755),
                      ("dist-package/lib/x.js", b"x", 0o644)])
evil_tgz = tarball([("dist-package/../../escaped", b"evil", 0o644)])
codex_tgz = b"fake codex package"
cline_tgz = b"fake cline package"

# Patch the fixture: claude/cursor (linux-x64 and linux-arm64) and codex take
# the fixture digests; cline loses its integrity and becomes an exception.
text = text.replace(inst["claude"]["sha256"]["linux-x64"], sha256(claude_bin))
text = text.replace(inst["cursor"]["sha256"]["linux-x64"], sha256(cursor_tgz))
text = text.replace(inst["cursor"]["sha256"]["linux-arm64"], sha256(evil_tgz))
text = text.replace(inst["codex"]["integrity"], sri(codex_tgz))
text = text.replace('integrity = "%s"' % inst["cline"]["integrity"], 'unverified = "fixture exception"')
fixture = os.path.join(SCRATCH, "providers.toml")
with open(fixture, "w") as fh:
    fh.write(text)
model = kinds.load(fixture)
check("the fixture providers.toml validates (an unverified exception is legal data)", True)

for cli, plat, data in (("claude", "linux-x64", claude_bin), ("grok", "linux-x64", b"tampered grok"),
                        ("cursor", "linux-x64", cursor_tgz), ("cursor", "linux-arm64", evil_tgz)):
    i = model.clis[cli]["install"]
    serve(installer._expand(i["url"], i, i["platforms"][plat]), data)
for cli, data in (("codex", codex_tgz), ("opencode", b"tampered opencode"), ("cline", cline_tgz)):
    serve(installer.npm_tarball_url(model.clis[cli]["install"]), data)


def run(cli, plat="linux-x64", allow=False):
    home = os.path.join(SCRATCH, "home-%s-%s-%s" % (cli, plat, allow))
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    os.environ["HOME"] = home
    if os.path.exists(LOG):
        os.remove(LOG)
    env = {"HOME": home, "PATH": BIN + ":/usr/bin:/bin", "XAI_API_KEY": PLANTED, "GH_TOKEN": PLANTED}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = installer.install_one(model, cli, env, allow_unverified=allow, plat=plat)
    npm_log = open(LOG).read() if os.path.exists(LOG) else ""
    return result, out.getvalue(), home, npm_log


def tree(home):
    return sorted(os.path.relpath(os.path.join(d, f), home) for d, _, fs in os.walk(home) for f in fs)


# binary: a matching digest installs, a mismatch installs nothing
ok_, out, home, _ = run("claude")
dest = os.path.join(home, ".local", "bin", "claude")
check("binary: a matching sha256 installs ~/.local/bin/claude", ok_ and os.path.isfile(dest), out)
check("binary: the installed file is the verified artifact, mode 755",
      os.path.isfile(dest) and open(dest, "rb").read() == claude_bin and stat.S_IMODE(os.stat(dest).st_mode) == 0o755)
ok_, out, home, _ = run("grok")
check("binary: a checksum mismatch is refused", not ok_ and "checksum mismatch" in out, out)
check("binary: a refused artifact leaves nothing in HOME", tree(home) == [], str(tree(home)))
ok_, out, home, _ = run("claude", plat="windows-x64")
check("binary: a platform without a pinned digest is refused", not ok_ and "no pinned artifact for windows-x64" in out, out)

# tarball: unpacked into the versioned directory and linked; traversal refused
ok_, out, home, _ = run("cursor")
link = os.path.join(home, ".local", "bin", "cursor-agent")
check("tarball: a matching sha256 unpacks and links cursor-agent and agent",
      ok_ and os.path.islink(link) and os.path.islink(os.path.join(home, ".local", "bin", "agent")), out)
check("tarball: the link points into the versioned directory",
      os.path.realpath(link).startswith(os.path.realpath(os.path.join(home, ".local", "share", "cursor-agent", "versions",
                                                                       model.clis["cursor"]["install"]["version"]))))
ok_, out, home, _ = run("cursor", plat="linux-arm64")
check("tarball: an entry leaving the archive is refused", not ok_ and "refusing an archive entry" in out, out)
check("tarball: nothing escaped and no staging is left", not os.path.exists(os.path.join(SCRATCH, "escaped"))
      and not any(".agentkit-new" in p for p in tree(home)), str(tree(home)))

# npm: the pinned integrity is checked before npm runs; npm installs that file
ok_, out, home, npm_log = run("codex")
check("npm: a matching integrity runs npm install -g <the verified tarball>",
      ok_ and "NPM install -g " in npm_log and npm_log.split("NPM install -g ", 1)[1].split()[0].endswith("codex-0.158.0.tgz"),
      npm_log or out)
check("npm: npm never sees a key variable", "NPM-ENV" not in npm_log, npm_log)
check("npm: no planted key value reaches the output", PLANTED not in out and PLANTED not in npm_log)
ok_, out, home, npm_log = run("opencode")
check("npm: an integrity mismatch is refused before npm runs", not ok_ and "checksum mismatch" in out and npm_log == "",
      out + npm_log)

# an unverified exception needs --allow-unverified
ok_, out, home, npm_log = run("cline")
check("unverified: refused without --allow-unverified", not ok_ and "--allow-unverified" in out and npm_log == "", out)
ok_, out, home, npm_log = run("cline", allow=True)
check("unverified: installs with --allow-unverified and says so", ok_ and "UNVERIFIED" in out and "NPM install -g" in npm_log, out)

# links: a foreign ~/.local/bin/agent is left alone; the kit's own link is replaced
home = os.path.join(SCRATCH, "home-links")
shutil.rmtree(home, ignore_errors=True)
os.makedirs(os.path.join(home, ".local", "bin"))
foreign = os.path.join(home, ".local", "bin", "agent")
with open(foreign, "w") as fh:
    fh.write("#!/bin/sh\necho another tool\n")
os.environ["HOME"] = home
env = {"HOME": home, "PATH": BIN + ":/usr/bin:/bin"}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    first = installer.install_one(model, "cursor", env, plat="linux-x64")
check("links: a foreign ~/.local/bin/agent is left alone and reported",
      first and not os.path.islink(foreign) and open(foreign).read().endswith("another tool\n")
      and "left %s alone" % foreign in out.getvalue(), out.getvalue())
link = os.path.join(home, ".local", "bin", "cursor-agent")
os.remove(link)
os.symlink(os.path.join(home, ".local", "share", "cursor-agent", "versions", "old", "cursor-agent"), link)
os.makedirs(os.path.join(home, ".local", "share", "cursor-agent", "versions", "old"))
with contextlib.redirect_stdout(io.StringIO()):
    again = installer._install_binary("cursor", model.clis["cursor"], model.clis["cursor"]["install"], "linux-x64",
                                      os.path.join(SCRATCH, "tmp-links"), env, False) \
        if os.makedirs(os.path.join(SCRATCH, "tmp-links"), exist_ok=True) is None else False
check("links: a link this kit made (into its versions directory) is replaced",
      again and os.path.realpath(link).endswith(os.path.join(model.clis["cursor"]["install"]["version"], "cursor-agent")),
      os.path.realpath(link))
check("tarball: a reinstall leaves no .agentkit-old or .agentkit-new behind",
      not any(p.endswith((".agentkit-old", ".agentkit-new"))
              for p in os.listdir(os.path.join(home, ".local", "share", "cursor-agent", "versions"))))
