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
PLANTED_LOGIN = "PLANTED-TOKEN-7f3a9c0001"
PLANTED_PROVIDER = "PLANTED-KEY-7f3a9c0002"
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


def login(path, token=PLANTED_LOGIN, **extra):
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
    env = {"HOME": HOME, "USERPROFILE": HOME, "PATH": os.environ.get("PATH", ""), "AGENTKIT_KEYCHAIN": "off",
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
ENV = env_for({"ZAI_CODING_API_KEY": PLANTED_PROVIDER, "ZAI_CODING_API_KEY_2": PLANTED_PROVIDER + "-2"})

code, rows = rows_of([], ENV)
order = [(r["cli"], r["profile"]) for r in rows]
check("usage core: one row per credential identity in the documented order",
      order == [("claude", "@default"), ("claude", "@2"), ("claude", "@work"), ("codex", "@default"), ("codex", "@work"),
                ("cursor", "@default"), ("cursor", "@work"), ("zai", "@default"), ("zai", "@2")], str(order))
moved = env_for({"ZAI_CODING_API_KEY": PLANTED_PROVIDER, "CLAUDE_CONFIG_DIR": os.path.join(PROFILES, "claude", "work")})
_c, moved_rows = rows_of(["claude"], moved)
check("usage core: a default home moved onto a profile directory is one account (no @default row twice)",
      [r["profile"] for r in moved_rows] == ["@2", "@work"], str([r["profile"] for r in moved_rows]))
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
      text.startswith("  PROFILE") and "5-hour" in text and "42%" in text and "in 2h 14m" in text, text[:300])
check("usage core: unsupported rows print n/d with the reason", "n/d" in text and "web session" in text)
check("usage core: a second run is byte-identical", run([], ENV)[1] == text)
lines = text.splitlines()
titles = [line for line in lines if line and not line.startswith(" ") and not line.startswith("n/d")]
check("usage core: one titled block per CLI or provider, in row order, the human name next to the id",
      [t.split()[0] for t in titles] == ["claude", "codex", "zai"] and "Claude Code" in titles[0], str(titles))
check("usage core: a blank line separates the blocks and every account sits indented under its title",
      all(lines[lines.index(t) - 1] == "" for t in titles)
      and all(line.startswith("  @") for line in lines if "@" in line and not line.startswith("n/d")), text)
check("usage core: the id of the CLI is not repeated on its account rows", not any(line.startswith("claude  @") for line in lines))
fit = usage.Platform("linux", True, "utf-8", {"TERM": "xterm"}, 60)
narrow = run([], ENV, platform=fit)[1]
check("usage core: on a terminal every line fits its width (notes are shortened, never wrapped)",
      all(len(usage._visible(line)) <= 60 for line in narrow.splitlines()), narrow)
check("usage core: -v keeps every note whole, even on a narrow terminal",
      "usage is only available through the Cursor web session" in run(["-v"], ENV, platform=fit)[1])
check("usage core: -v and --verbose are the same option", run(["-v"], ENV)[1] == run(["--verbose"], ENV)[1])
check("usage core: the table's short notes never reach --json", "_short" not in run(["--json"], ENV)[1])


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
      PLANTED_LOGIN not in everything and PLANTED_PROVIDER not in everything, "a planted value leaked")
sent = [r["auth"] for r in server.requests if r["auth"]]
check("usage core: the credential reached the endpoint (as a bearer, hashed in the log)",
      hashlib.sha256(("Bearer " + PLANTED_LOGIN).encode()).hexdigest()[:12] in sent)
state = tree_state(TMP)
run([], ENV)
run(["--json"], ENV)
check("usage core: a run changes nothing under the home or the profiles", [s for s in tree_state(TMP) if s[0] != doc_path] == [s for s in state if s[0] != doc_path])


# ------------------------------------------------------------- resilience

import time  # noqa: E402


class FakeBoom(FakeOAuth):
    id = "fake-boom"

    def parse(self, doc):
        raise RuntimeError("parser bug")


class FakeScoped(FakeOAuth):
    id = "fake-scoped"
    required_scope = "user:profile"


usage.register(FakeBoom())
usage.register(FakeScoped())
leak_probe = ""


def codex_row(routes, extra_args=None, adapter=None, env_extra=None, model=None):
    server.set_routes(routes)
    return rows_of(["codex", "@default"] + (extra_args or []), env_for(env_extra))


GOOD = {"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}}
ENV_CODEX = {"AGENTKIT_USAGE_URL_FAKE_OAUTH": server.base + "/codex"}
MODES = [
    ("a 500 is HTTP 500", {"/codex": {"status": 500, "body": "boom"}}, "error", "HTTP 500"),
    ("a 429 is rate_limited", {"/codex": {"status": 429, "body": "{}"}}, "rate_limited", "rate limited"),
    ("a 401 is no_scope with guidance", {"/codex": {"status": 401, "body": "{}"}}, "no_scope", "HTTP 401"),
    ("a 403 is no_scope with guidance", {"/codex": {"status": 403, "body": "{}"}}, "no_scope", "HTTP 403"),
    ("a redirect is never followed", {"/codex": {"redirect": "/other"}, "/other": {"json": WINDOWS_OK}}, "error", "unexpected redirect"),
    ("an oversized body is refused", {"/codex": {"size": 2 * 1024 * 1024}}, "error", "response too large"),
    ("truncated JSON is an unexpected shape", {"/codex": {"body": "{\"plan\": "}}, "error", "unexpected response shape"),
    ("an empty body is an unexpected shape", {"/codex": {"body": ""}}, "error", "unexpected response shape"),
    ("a wrong shape is an unexpected shape", {"/codex": {"json": {"windows": "nope"}}}, "error", "unexpected response shape"),
    ("a missing path (404) is HTTP 404", {}, "error", "HTTP 404"),
]
for label, routes, want_status, want_text in MODES:
    server.requests[:] = []
    _, rows = codex_row(routes, env_extra=ENV_CODEX)
    row = rows[0]
    leak_probe += json.dumps(row)
    check("usage resilience: %s" % label, row["status"] == want_status and want_text in (row["error"] or ""), str(row))
check("usage resilience: a redirect target is never requested", "/other" not in [r["path"] for r in server.requests])

# slow endpoint: the per-request timeout bounds the wait
server.requests[:] = []
started = time.time()
_, rows = codex_row({"/codex": {"json": WINDOWS_OK, "delay": 3}}, ["--timeout", "1"], env_extra=ENV_CODEX)
elapsed = time.time() - started
check("usage resilience: a slow endpoint times out at --timeout", rows[0]["error"] == "timed out after 1s" and elapsed < 2.8,
      "%s %.1f" % (rows[0], elapsed))

# a parser bug costs one row, not the run
boom = copy.deepcopy(MODEL.data)
boom["clis"]["codex"]["usage"]["adapter"] = "fake-boom"
boom_model = kinds.Model(boom, "providers.toml")
server.set_routes(GOOD)
code, out, _ = run(["--json"], env_for({"AGENTKIT_USAGE_URL_FAKE_BOOM": server.base + "/codex"}), model=boom_model)
rows = json.loads(out)["rows"]
codex_default = [r for r in rows if r["cli"] == "codex" and r["profile"] == "@default"][0]
claude_default = [r for r in rows if r["cli"] == "claude" and r["profile"] == "@default"][0]
check("usage resilience: an unexpected parser exception becomes an error row", codex_default["error"] == "internal error (RuntimeError)", str(codex_default))
check("usage resilience: the other rows are unaffected", claude_default["status"] == "ok" and code == 1)

# scopes known before any request
scoped = copy.deepcopy(MODEL.data)
scoped["clis"]["codex"]["usage"]["adapter"] = "fake-scoped"
login(os.path.join(HOME, ".codex", "auth.json"), exp=NOW + 3600, scopes=["user:inference"])
server.requests[:] = []
_, out, _ = run(["--json", "codex", "@default"], env_for({"AGENTKIT_USAGE_URL_FAKE_SCOPED": server.base + "/codex"}), model=kinds.Model(scoped, "providers.toml"))
row = json.loads(out)["rows"][0]
check("usage resilience: a login lacking the needed scope is no_scope without a request",
      row["status"] == "no_scope" and "user:profile" in row["error"] and not server.requests, str(row))
login(os.path.join(HOME, ".codex", "auth.json"), exp=NOW + 3600)

# healthy rows still print when another fails
server.set_routes({"/claude": {"status": 500, "body": "x"}, "/zai": {"json": ZAI_OK}})
code2, text2, _ = run([], ENV)
check("usage resilience: the table still prints healthy rows next to failing ones",
      "tokens" in text2 and "48%" in text2 and "HTTP 500" in text2 and code2 == 1, text2[:400])
leak_probe += text2

# parallel: ten logins against a 1 s endpoint finish far sooner than ten seconds
for i in range(1, 9):
    login(os.path.join(PROFILES, "claude", "r%d" % i, ".credentials.json"))
server.set_routes({"/claude": {"json": WINDOWS_OK, "delay": 1}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})
server.requests[:] = []
started = time.time()
code, rows = rows_of(["claude"], ENV)
elapsed = time.time() - started
served = len([r for r in server.requests if r["path"] == "/claude"])
check("usage resilience: ten slow rows run in parallel", served >= 10 and elapsed < 4.5, "%d requests in %.1fs" % (served, elapsed))
check("usage resilience: results keep the documented row order", [r["profile"] for r in rows] ==
      ["@default", "@2"] + ["@r%d" % i for i in range(1, 9)] + ["@work"], str([r["profile"] for r in rows]))
server.set_routes(GOOD)
import shutil  # noqa: E402
for i in range(1, 9):
    shutil.rmtree(os.path.join(PROFILES, "claude", "r%d" % i))

# exit-code matrix
check("usage resilience: exit codes - ok 0, problem 1, usage 2, nothing 3",
      run(["cursor"], ENV)[0] == 0 and run(["claude", "@2"], ENV)[0] == 1 and run(["--bogus"], ENV)[0] == 2
      and run(["claude", "@nowhere"], ENV)[0] == 3)
check("usage resilience: no failure message carries a token", PLANTED_LOGIN not in leak_probe and PLANTED_PROVIDER not in leak_probe)


# --------------------------------------------------------------- platforms

PLATFORMS = [usage.Platform(n, False, "utf-8", {}) for n in ("linux", "macos", "windows")]
rendered = [run(["claude", "@default"], ENV, platform=p)[1] for p in PLATFORMS]
check("usage platform: the table is identical on Linux, macOS and Windows once colour is off",
      len(set(rendered)) == 1, "\n---\n".join(rendered))
check("usage platform: JSON is identical on all three",
      len({run(["--json", "claude", "@default"], ENV, platform=p)[1] for p in PLATFORMS}) == 1)
check("usage platform: colour needs a terminal everywhere, and on Windows one that announces itself",
      [usage.Platform(n, True, "utf-8", {"TERM": "xterm"}).supports_color() for n in ("linux", "macos", "windows")] == [True, True, True]
      and not usage.Platform("windows", True, "utf-8", {}).supports_color()
      and not usage.Platform("windows", False, "utf-8", {"WT_SESSION": "1"}).supports_color())
check("usage platform: a legacy console encoding gets the ASCII bar, UTF-8 the blocks",
      "#" in run(["claude", "@default"], ENV, platform=usage.Platform("windows", False, "cp1252", {}))[1]
      and "\u2588" in run(["claude", "@default"], ENV, platform=usage.Platform("windows", False, "utf-8", {}))[1])

# Windows: no HOME, only USERPROFILE; a login file with a BOM and CRLF line ends
win_env = {k: v for k, v in ENV.items() if k != "HOME"}
win_env["USERPROFILE"] = HOME
bom = "\ufeff" + json.dumps({"token": PLANTED_LOGIN}, indent=2).replace("\n", "\r\n")
with open(os.path.join(HOME, ".claude", ".credentials.json"), "wb") as handle:
    handle.write(bom.encode("utf-8"))
check("usage platform: the home comes from USERPROFILE when HOME is unset (Windows)",
      rows_of(["claude", "@default"], win_env)[1][0]["status"] == "ok")
check("usage platform: a UTF-8 BOM and CRLF in a login file are tolerated", rows_of(["claude", "@default"], win_env)[1][0]["status"] == "ok")
login(os.path.join(HOME, ".claude", ".credentials.json"))


class CP1252Out(io.StringIO):
    encoding = "cp1252"

    def write(self, text):
        text.encode("cp1252")        # what a legacy console does: raises on what it cannot show
        return io.StringIO.write(self, text)


odd = copy.deepcopy(WINDOWS_OK)
odd["plan"] = "Max \u2605 5x"
server.set_routes({"/claude": {"json": odd}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})
legacy = CP1252Out()
code = usage.main(MODEL, ["claude", "@default"], ENV, now=NOW, stdout=legacy, platform=usage.Platform("windows", False, "cp1252", {}))
check("usage platform: a character the console cannot show is replaced, never raised", code == 0 and "Max ? 5x" in legacy.getvalue(), legacy.getvalue()[:200])
server.set_routes({"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})

# no POSIX-only primitive in the shared code path (also enforced by the scope and the gate)
import re  # noqa: E402
source = open(os.path.join(ROOT, "lib", "usage.py"), encoding="utf-8").read()
banned = re.findall(r"import (?:fcntl|pwd|grp|termios|resource)\b|os\.fork|signal\.alarm|os\.getuid\b|/home/|C:\\\\", source)
check("usage platform: lib/usage.py has no POSIX-only import or hardcoded path", not banned, str(banned))


# --------------------------------------------------- review hardening checks

esc = copy.deepcopy(WINDOWS_OK)
esc["plan"] = "max\x1b]0;pwned\x07\x1b[2J" + "x" * 200
esc["windows"][0]["label"] = "5-hour\x1b[31m"
server.set_routes({"/claude": {"json": esc}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})
code, text, _ = run(["claude", "@default"], ENV)
code_j, out_j, _ = run(["--json", "claude", "@default"], ENV)
check("usage review: control characters from a response never reach the terminal (table and JSON)",
      "\x1b" not in text and "\x07" not in text and "\x1b" not in out_j and "\x07" not in out_j, repr(text[:120]))
check("usage review: a vendor-supplied plan label is capped", len(json.loads(out_j)["rows"][0]["plan"]) <= 60)
server.set_routes({"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})

big = os.path.join(HOME, ".claude", ".credentials.json")
with open(big, "wb") as handle:
    handle.write(b"{\"claudeAiOauth\": {\"accessToken\": \"" + b"a" * (2 * 1024 * 1024) + b"\"}}")
code, rows = rows_of(["claude", "@default"], ENV)
check("usage review: an oversized login file is an error row, not read whole", rows[0]["status"] == "error" and "large" in rows[0]["error"], str(rows[0]))
login(big)

saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "NO_PROXY", "no_proxy")}
try:
    for k in saved:
        os.environ.pop(k, None)
    os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"      # a dead proxy
    os.environ["https_proxy"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    code, rows = rows_of(["claude", "@default"], ENV)
    check("usage review: a loopback override ignores the proxy variables of the environment",
          rows[0]["status"] == "ok", str(rows[0]))
finally:
    for k in saved:
        os.environ.pop(k, None)
        if saved[k] is not None:
            os.environ[k] = saved[k]


# non-finite and absurd numbers from a response never become a percentage or a crash
for label, doc in (("NaN", {"plan": "x", "windows": [{"id": "5h", "label": "5-hour", "used": float("nan"), "reset": None}]}),
                   ("Infinity", {"plan": "x", "windows": [{"id": "5h", "label": "5-hour", "used": float("inf"), "reset": None}]})):
    server.set_routes({"/claude": {"json": doc}})
    row = rows_of(["claude", "@default"], ENV)[1][0]
    check("usage review: a %s utilization is an unexpected shape, not 100 %%" % label,
          row["status"] == "error" and row["error"] == "unexpected response shape", str(row))
server.set_routes({"/claude": {"json": {"plan": "x", "windows": [{"id": "5h", "label": "5-hour", "used": 5, "reset": 10 ** 30}]}}})
row = rows_of(["claude", "@default"], ENV)[1][0]
check("usage review: an out-of-range reset time becomes unknown, not an error",
      row["status"] == "ok" and row["windows"][0]["resets_at"] is None, str(row))
server.set_routes({"/claude": {"json": WINDOWS_OK}, "/codex": {"json": WINDOWS_OK}, "/zai": {"json": ZAI_OK}})

# The bar: fixed width; any nonzero use is visible; below 100 never full.
for pct in (0, 1, 4, 14, 50, 99, 100):
    for utf8 in (True, False):
        bar = usage._bar(pct, utf8)
        mode = "utf-8" if utf8 else "ascii"
        empty = "░" if utf8 else "-"
        check("usage bar %s %d%%: ten cells wide" % (mode, pct), len(bar) == 10, repr(bar))
        check("usage bar %s %d%%: empty only at 0%%" % (mode, pct), (bar == empty * 10) == (pct == 0), repr(bar))
        check("usage bar %s %d%%: full only at 100%%" % (mode, pct), (bar == ("█" if utf8 else "#") * 10) == (pct == 100), repr(bar))
check("usage bar: 4% shows the thinnest mark", usage._bar(4, True).startswith(("▏", "▎", "▍")), repr(usage._bar(4, True)))
check("usage bar: 14% draws more than 10%", usage._bar(14, True) != usage._bar(10, True), repr(usage._bar(14, True)))
check("usage bar: 1% in ASCII is one '#'", usage._bar(1, False) == "#" + "-" * 9, repr(usage._bar(1, False)))
check("usage bar: 99% is not full in either mode", usage._bar(99, True) != "█" * 10 and usage._bar(99, False) != "#" * 10, "")

server.stop()
if FAILS:
    sys.exit(1)
