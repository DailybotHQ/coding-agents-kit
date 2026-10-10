"""Bash-free checks for `ak usage` (lib/usage.py): the pipeline, enumeration,
deduplication, rendering, --json, filters, exit codes, secrecy and read-only
behaviour, against a loopback fake endpoint and a fake adapter.

    python3 tests/py/usage_checks.py            (any OS; no bash, no network)

Prints one `ok <name>` / `FAIL <name>: <why>` line per check and exits 1 when
any check failed, so the `usage` scope folds the lines in and the Windows CI
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
sys.path.insert(0, HERE)

import common  # noqa: E402
import kinds  # noqa: E402
import usage  # noqa: E402
from common import AkError  # noqa: E402
from fake_usage_server import FakeUsageServer  # noqa: E402

FAILS = []
TOKEN = "PLANTED-TOKEN-7f3a9c0001"
KEY = "PLANTED-KEY-7f3a9c0002"
NOW = 1790000000.0


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


# ------------------------------------------------------------ fake adapter

class FakeOAuth(usage.Adapter):
    id = "fake-oauth"

    def credential_from_file(self, doc):
        if "token" not in doc:
            return usage.Failure("no_login", "the login file has no token")
        return usage.Credential(doc["token"], doc.get("exp"), doc.get("scopes"), doc.get("plan"))

    def parse(self, doc):
        try:
            wins = [usage.window(w["id"], w["label"], w["used"], usage.parse_time(w.get("reset")), w.get("secs"))
                    for w in doc["windows"]]
        except (KeyError, TypeError):
            raise usage.ShapeError("shape")
        return doc.get("plan"), wins


class FakeKey(FakeOAuth):
    id = "fake-key"


usage.register(FakeOAuth())
usage.register(FakeKey())


def fake_model():
    """The shipped model with two fake usage sources (not validated: the fake
    adapters are not in USAGE_ADAPTERS, so they can never come from the file)."""
    data = copy.deepcopy(kinds.load().data)
    data["clis"]["claude"]["usage"] = {"adapter": "fake-oauth", "url": "https://example.invalid/claude",
                                       "headers": {"authorization": "Bearer {token}"}, "credential": "file",
                                       "files": ["home:.credentials.json"]}
    data["clis"]["codex"]["usage"] = {"adapter": "fake-oauth", "url": "https://example.invalid/codex",
                                      "headers": {"authorization": "Bearer {token}"}, "credential": "file",
                                      "files": ["home:auth.json"]}
    data["providers"]["zai"]["usage"] = {"adapter": "fake-key", "url": "https://example.invalid/zai",
                                         "headers": {"authorization": "Bearer {token}"}, "credential": "env"}
    return kinds.Model(data, "providers.toml")


# ---------------------------------------------------------------- sandbox

TMP = tempfile.mkdtemp(prefix="agentkit-usage-")
HOME = os.path.join(TMP, "home")
PROFILES = os.path.join(TMP, "profiles")
os.makedirs(HOME)
os.environ["AGENTKIT_PROFILES_DIR"] = PROFILES
os.environ["HOME"] = HOME
os.environ["USERPROFILE"] = HOME
INSTALLED = set(["claude", "codex", "cursor"])
usage._installed = lambda model, env, cli_name: cli_name in INSTALLED


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def login(path, token=TOKEN, **extra):
    doc = {"token": token}
    doc.update(extra)
    write(path, json.dumps(doc))


def tree_state(base):
    state = []
    for dirpath, _dirs, files in sorted(os.walk(base)):
        for name in sorted(files):
            p = os.path.join(dirpath, name)
            with open(p, "rb") as handle:
                state.append((p, hashlib.sha256(handle.read()).hexdigest(), os.stat(p).st_mtime))
    return state


WINDOWS_OK = {"plan": "max", "windows": [
    {"id": "5h", "label": "5-hour", "used": 42, "reset": NOW + 8040, "secs": 18000},
    {"id": "7d", "label": "7-day", "used": 13.5, "reset": NOW + 90000, "secs": 604800}]}
ZAI_OK = {"plan": "lite", "windows": [{"id": "tokens", "label": "tokens", "used": 48, "reset": NOW + 4800, "secs": None}]}

server = FakeUsageServer(routes={"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK},
                                 "/zai": {"json": ZAI_OK}}).start()
MODEL = fake_model()


def env_for(extra=None):
    env = {"HOME": HOME, "USERPROFILE": HOME, "PATH": os.environ.get("PATH", ""),
           "AGENTKIT_USAGE_URL_FAKE_OAUTH": server.base + "/claude",
           "AGENTKIT_USAGE_URL_FAKE_KEY": server.base + "/zai"}
    env.update(extra or {})
    return env


def run(args, env=None, platform=None, now=NOW, model=None):
    out = io.StringIO()
    err = io.StringIO()
    saved = sys.stderr
    sys.stderr = err
    try:
        code = usage.main(model or MODEL, args, env or env_for(), now=now, stdout=out,
                          platform=platform or usage.Platform("linux", False, "utf-8", {}))
    except AkError as exc:
        code = exc.code
        err.write(str(exc))
    finally:
        sys.stderr = saved
    return code, out.getvalue(), err.getvalue()


def rows_of(args, env=None):
    code, out, _ = run(["--json"] + args, env)
    return code, json.loads(out)["rows"] if out.strip() else []


# ------------------------------------------------------------------- core

login(os.path.join(HOME, ".claude", ".credentials.json"))
login(os.path.join(HOME, ".codex", "auth.json"), exp=NOW + 3600)
login(os.path.join(PROFILES, "claude", "work", ".credentials.json"))
login(os.path.join(PROFILES, "claude", "2", ".credentials.json"))
login(os.path.join(PROFILES, "codex", "work", "auth.json"))
os.makedirs(os.path.join(PROFILES, "cursor", "work"))
ENV = env_for({"ZAI_CODING_API_KEY": KEY, "ZAI_CODING_API_KEY_2": KEY + "-2"})

code, rows = rows_of([], ENV)
order = [(r["cli"], r["profile"]) for r in rows]
check("usage core: one row per credential identity in the documented order",
      order == [("claude", "@default"), ("claude", "@2"), ("claude", "@work"), ("codex", "@default"), ("codex", "@work"),
                ("cursor", "@default"), ("cursor", "@work"), ("zai", "@default"), ("zai", "@2")], str(order))
zai = [r for r in rows if r["cli"] == "zai"]
check("usage core: four glm kinds of one key collapse into one row",
      len(zai) == 2 and zai[0]["kinds"] == ["claude-glm", "codex-glm", "opencode-glm", "pi-glm"], str(zai))
check("usage core: ok rows carry the provider's own windows",
      rows[0]["status"] == "ok" and [w["id"] for w in rows[0]["windows"]] == ["5h", "7d"] and rows[0]["plan"] == "max")
check("usage core: used_pct, reset and window length are normalised",
      rows[0]["windows"][0]["used_pct"] == 42 and rows[0]["windows"][0]["resets_at"] == usage.iso_utc(NOW + 8040)
      and rows[0]["windows"][0]["window_seconds"] == 18000 and rows[0]["windows"][1]["used_pct"] == 13.5)
cursor = [r for r in rows if r["cli"] == "cursor"]
check("usage core: unsupported rows say why and carry no windows",
      all(r["status"] == "unsupported" and r["reason"] and r["windows"] == [] for r in cursor))
check("usage core: exit 0 when every row is ok or unsupported", code == 0, str(code))

text = run([], ENV)[1]
check("usage core: the table names the columns and a bar with its percent",
      text.startswith("CLI") and "5-hour" in text and "42%" in text and "in 2h 14m" in text, text[:300])
check("usage core: unsupported rows print n/d with the reason", "n/d" in text and "web session" in text)
check("usage core: a second run is byte-identical", run([], ENV)[1] == text)

# --json against the schema
code, out, _ = run(["--json"], ENV)
doc_path = os.path.join(TMP, "usage.json")
write(doc_path, out)
proc = subprocess.run([sys.executable, os.path.join(HERE, "schema_check.py"),
                       os.path.join(ROOT, "docs", "schema", "usage-v1.json"), doc_path],
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
check("usage json: output validates against docs/schema/usage-v1.json", proc.stdout.decode().strip() == "valid",
      proc.stdout.decode()[:300])
doc = json.loads(out)
check("usage json: schema usage-v1, interface 1, UTC timestamp",
      doc["schema"] == "usage-v1" and doc["interface"] == 1 and doc["generated_at"] == usage.iso_utc(NOW))
check("usage json: one JSON object and no ANSI", out.lstrip().startswith("{") and "\x1b" not in out)

# filters
_, only_claude = rows_of(["claude"], ENV)
check("usage core: a CLI filter keeps only that CLI", {r["cli"] for r in only_claude} == {"claude"})
_, only_glm = rows_of(["claude-glm"], ENV)
check("usage core: a provider kind filter selects the provider rows", {r["cli"] for r in only_glm} == {"zai"})
_, only_work = rows_of(["@work"], ENV)
check("usage core: a profile filter keeps only that profile", {r["profile"] for r in only_work} == {"@work"})
_, both = rows_of(["codex", "@work"], ENV)
check("usage core: kind and profile filters combine", [(r["cli"], r["profile"]) for r in both] == [("codex", "@work")])
check("usage core: @default and @1 name the same profile", rows_of(["claude", "@1"], ENV)[1] == rows_of(["claude", "@default"], ENV)[1])
check("usage core: an unknown kind is a usage error (exit 2)", run(["nope"], ENV)[0] == 2)
check("usage core: an unknown option is a usage error (exit 2)", run(["--bogus"], ENV)[0] == 2)
check("usage core: two profiles are a usage error", run(["@a", "@b"], ENV)[0] == 2)
check("usage core: a bad --timeout is a usage error", run(["--timeout", "0"], ENV)[0] == 2 and run(["--timeout"], ENV)[0] == 2)
check("usage core: --help exits 0 and prints the grammar", run(["--help"], ENV)[0] == 0 and "ak usage" in run(["--help"], ENV)[1])
code, out, err = run(["claude", "@nowhere"], ENV)
check("usage core: nothing to report exits 3 with a hint", code == 3 and "nothing to report" in err, "%s %s" % (code, err))

# exit codes
login(os.path.join(HOME, ".claude", ".credentials.json"), exp=NOW - 10)
before = len(server.requests)
code, rows = rows_of(["claude", "@default"], ENV)
check("usage core: an expired login is reported without any request",
      rows[0]["status"] == "expired" and len(server.requests) == before and code == 1, str(rows[0]))
login(os.path.join(HOME, ".claude", ".credentials.json"))
os.remove(os.path.join(PROFILES, "claude", "2", ".credentials.json"))
code, rows = rows_of(["claude", "@2"], ENV)
check("usage core: a profile without a login is no_login (exit 1)", rows[0]["status"] == "no_login" and code == 1)
write(os.path.join(HOME, ".codex", "auth.json"), "{ not json")
_, rows = rows_of(["codex", "@default"], ENV)
check("usage core: an unreadable login file is an error row, not a crash", rows[0]["status"] == "error")
login(os.path.join(HOME, ".codex", "auth.json"), exp=NOW + 3600)
server.set_routes({"/claude": {"json": {"unexpected": True}}, "/zai": {"json": ZAI_OK}})
_, rows = rows_of(["claude", "@default"], ENV)
check("usage core: a changed response shape is error: unexpected response shape",
      rows[0]["status"] == "error" and rows[0]["error"] == "unexpected response shape", str(rows[0]))
server.set_routes({"/claude": {"status": 500, "body": "boom"}})
_, rows = rows_of(["claude", "@default"], ENV)
check("usage core: an HTTP error is reported with its code only", rows[0]["error"] == "HTTP 500", str(rows[0]))
server.set_routes({"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})

# network rules
check("usage core: an override to a non-loopback host is refused (exit 2)",
      run(["claude", "@default"], env_for({"AGENTKIT_USAGE_URL_FAKE_OAUTH": "http://example.com/x"}))[0] == 2)
check("usage core: an override with a file scheme is refused (exit 2)",
      run(["claude", "@default"], env_for({"AGENTKIT_USAGE_URL_FAKE_OAUTH": "file:///etc/passwd"}))[0] == 2)

# rendering: colour and ASCII fallback
tty = usage.Platform("linux", True, "utf-8", {"TERM": "xterm"})
check("usage core: colour only on a terminal", "\x1b[" in run(["claude", "@default"], ENV, platform=tty)[1]
      and "\x1b[" not in run(["claude", "@default"], ENV)[1])
check("usage core: --no-color and NO_COLOR switch it off",
      "\x1b[" not in run(["--no-color", "claude", "@default"], ENV, platform=tty)[1]
      and "\x1b[" not in run(["claude", "@default"], ENV, platform=usage.Platform("linux", True, "utf-8", {"NO_COLOR": "1"}))[1])
check("usage core: colour is off for TERM=dumb",
      "\x1b[" not in run(["claude", "@default"], ENV, platform=usage.Platform("linux", True, "utf-8", {"TERM": "dumb"}))[1])
ascii_out = run(["claude", "@default"], ENV, platform=usage.Platform("windows", False, "cp1252", {}))[1]
check("usage core: a non-UTF-8 console gets an ASCII bar", "#" in ascii_out and all(ord(c) < 128 for c in ascii_out), ascii_out[:200])
check("usage core: the UTF-8 bar uses block characters", "█" in run(["claude", "@default"], ENV)[1])
win = usage.Platform("windows", True, "utf-8", {"TERM": "xterm"})
check("usage core: Windows colour needs a terminal that announces itself",
      not usage.Platform("windows", True, "utf-8", {}).supports_color() and win.supports_color())

# secrecy and read-only
everything = ""
for args in ([], ["--json"], ["claude"], ["codex", "@work"], ["nope"], ["--timeout", "1"]):
    code, out, err = run(args, ENV)
    everything += out + err
check("usage core: no token or key value reaches any output or message",
      TOKEN not in everything and KEY not in everything, "a planted value leaked")
sent = [r["auth"] for r in server.requests if r["auth"]]
check("usage core: the credential reached the endpoint (as a bearer, hashed in the log)",
      hashlib.sha256(("Bearer " + TOKEN).encode()).hexdigest()[:12] in sent)
state = tree_state(TMP)
run([], ENV)
run(["--json"], ENV)
check("usage core: a run changes nothing under the home or the profiles", [s for s in tree_state(TMP) if s[0] != doc_path] == [s for s in state if s[0] != doc_path])

server.stop()
if FAILS:
    sys.exit(1)
