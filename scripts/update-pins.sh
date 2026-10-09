#!/usr/bin/env bash
# scripts/update-pins.sh — maintainer tool: re-derive the digests of every
# pinned CLI version in providers.toml from its source and compare.
#
#   bash scripts/update-pins.sh            # compare; exit 1 on any difference
#
# Sources, per channel (the comment above each [clis.<cli>.install] names it):
#   binary/tarball with a vendor manifest  claude: the release manifest.json
#   binary/tarball without one             cursor, grok: download each
#                                          platform's artifact and hash it
#                                          (trust on first use)
#   npm                                    the registry's dist.integrity
#
# To move a pin: change `version` (and the URL token if the vendor changed
# it), run this script, paste the fetched digests it prints, run it again
# until it reports no difference, then run `bash tests/run.sh kinds install`.
# It downloads into a private temporary directory, runs nothing it
# downloads, and never touches HOME. Needs network, curl and python3.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/agentkit-pins.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT

python3 - "${ROOT}" "${TMP}" <<'PY'
import json
import subprocess
import sys

root, tmp = sys.argv[1], sys.argv[2]
sys.path.insert(0, root + "/lib")
import installer  # noqa: E402
import kinds  # noqa: E402

model = kinds.load()
diff = 0


def fetch(url, dest):
    subprocess.run(["curl", "-fsSL", "--proto", "=https", "--tlsv1.2", "-o", dest, url], check=True)


def report(cli, plat, pinned, fetched):
    global diff
    same = pinned == fetched
    diff += 0 if same else 1
    print("%-9s %-12s %s  %s" % (cli, plat, "same" if same else "DIFF", fetched))


for cli in model.cli_names():
    inst = model.clis[cli]["install"]
    if inst["channel"] == "npm":
        url = "https://registry.npmjs.org/%s/%s" % (inst["package"], inst["version"])
        fetch(url, tmp + "/meta.json")
        with open(tmp + "/meta.json") as fh:
            report(cli, "npm", inst.get("integrity"), json.load(fh)["dist"]["integrity"])
        continue
    manifest = None
    if cli == "claude":
        fetch("https://downloads.claude.ai/claude-code-releases/%s/manifest.json" % inst["version"], tmp + "/m.json")
        with open(tmp + "/m.json") as fh:
            manifest = json.load(fh)["platforms"]
    for plat, token in sorted(inst["platforms"].items()):
        if manifest is not None:
            fetched = manifest[token]["checksum"]
        else:
            dest = tmp + "/artifact"
            fetch(installer._expand(inst["url"], inst, token), dest)
            fetched = installer.sha256_of(dest)
        report(cli, plat, inst["sha256"].get(plat), fetched)

print("differences: %d" % diff)
sys.exit(1 if diff else 0)
PY
