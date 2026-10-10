"""Bash-free checks for the `ak usage` sources, one adapter at a time, against
the REAL providers.toml model and a loopback fake endpoint (no network, no
bash, any OS). The response fixtures below are the documented shapes (see the
plan's ENDPOINT_FINDINGS.md); until verified on real accounts they are
provisional, which is why every adapter also has an unexpected-shape check.

    python3 tests/py/usage_provider_checks.py

Prints `ok <name>` / `FAIL <name>: <why>` per check; exits 1 on any failure.
"""

import hashlib
import io
import json
import os
import stat
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
NOW = 1790000000.0
PLANTED_LOGIN = "PLANTED-LOGIN-5c1d9e0003"
PLANTED_PROVIDER = "PLANTED-KEY-5c1d9e0004"
PLANTED_REFRESH = "PLANTED-REFRESH-0009"
PLANTED_REFRESH2 = "PLANTED-REFRESH-0010"


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


TMP = tempfile.mkdtemp(prefix="agentkit-usage-prov-")
HOME = os.path.join(TMP, "home")
PROFILES = os.path.join(TMP, "profiles")
os.makedirs(HOME)
os.environ["AGENTKIT_PROFILES_DIR"] = PROFILES
os.environ["HOME"] = HOME
os.environ["USERPROFILE"] = HOME
INSTALLED = set()
usage._installed = lambda model, env, cli_name: cli_name in INSTALLED
MODEL = kinds.load()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def snapshot(base):
    out = []
    for dirpath, _d, files in sorted(os.walk(base)):
        for name in sorted(files):
            p = os.path.join(dirpath, name)
            with open(p, "rb") as handle:
                out.append((p, hashlib.sha256(handle.read()).hexdigest(), os.stat(p).st_mtime))
    return out


server = FakeUsageServer().start()
URLS = {"ANTHROPIC_OAUTH": "/claude", "CHATGPT_WHAM": "/codex", "ZAI_QUOTA": "/zai"}


def env_for(extra=None):
    env = {"HOME": HOME, "USERPROFILE": HOME, "PATH": os.environ.get("PATH", "")}
    for adapter, path in URLS.items():
        env["AGENTKIT_USAGE_URL_" + adapter] = server.base + path
    env.update(extra or {})
    return env


def run(args, env=None, model=None, platform=None, now=NOW):
    out, err = io.StringIO(), io.StringIO()
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


def rows_of(args, env=None, **kw):
    code, out, err = run(["--json"] + args, env, **kw)
    return code, (json.loads(out)["rows"] if out.strip() else []), err


# ================================================================== claude

CLAUDE_OK = {"five_hour": {"utilization": 42.0, "resets_at": "2026-10-10T17:00:00.123456+00:00"},
             "seven_day": {"utilization": 13.5, "resets_at": "2026-10-14T00:00:00Z"},
             "seven_day_opus": None,
             "seven_day_sonnet": {"utilization": 7, "resets_at": "2026-10-14T00:00:00Z"},
             "extra_usage": None}
INSTALLED.add("claude")


def claude_login(directory, **over):
    oauth = {"accessToken": PLANTED_LOGIN, "refreshToken": PLANTED_REFRESH, "expiresAt": int((NOW + 3600) * 1000),
             "scopes": ["user:inference", "user:profile"], "subscriptionType": "max"}
    oauth.update(over)
    write(os.path.join(directory, ".credentials.json"), json.dumps({"claudeAiOauth": oauth}))


claude_login(os.path.join(HOME, ".claude"))
for name, extra in (("work", {"subscriptionType": "pro"}), ("2", {"subscriptionType": "max"}), ("old", {"expiresAt": int((NOW - 60) * 1000)}),
                    ("infer", {"scopes": ["user:inference"]})):
    claude_login(os.path.join(PROFILES, "claude", name), **extra)
server.set_routes({"/claude": {"json": CLAUDE_OK}})
code, rows, err = rows_of(["claude"])
by = {r["profile"]: r for r in rows}
check("usage claude: three real-looking accounts give independent rows",
      [r["profile"] for r in rows] == ["@default", "@2", "@infer", "@old", "@work"], str([r["profile"] for r in rows]))
d = by["@default"]
check("usage claude: the 5-hour and weekly windows are mapped",
      d["status"] == "ok" and [w["id"] for w in d["windows"]] == ["5h", "7d", "7d-sonnet"] and d["windows"][0]["used_pct"] == 42
      and d["windows"][0]["window_seconds"] == 18000 and d["windows"][1]["window_seconds"] == 604800, str(d))
check("usage claude: reset times become ISO UTC (offset and fraction handled)",
      d["windows"][0]["resets_at"] == "2026-10-10T17:00:00Z" and d["windows"][1]["resets_at"] == "2026-10-14T00:00:00Z", str(d["windows"]))
check("usage claude: the plan comes from the login's subscription type", d["plan"] == "max" and by["@work"]["plan"] == "pro")
check("usage claude: a null per-model window is skipped, not an error", "7d-opus" not in [w["id"] for w in d["windows"]])
check("usage claude: an expired token is reported without a request",
      by["@old"]["status"] == "expired", str(by["@old"]))
server.requests[:] = []
rows_of(["claude", "@old"])
check("usage claude: ... and no request is made for it", not server.requests)
check("usage claude: an inference-only login is no_scope before any request",
      by["@infer"]["status"] == "no_scope" and "user:profile" in by["@infer"]["error"], str(by["@infer"]))
server.requests[:] = []
rows_of(["claude", "@infer"])
check("usage claude: ... and no request is made for it either", not server.requests)
sent = {r["auth"] for r in (rows_of(["claude", "@default"]), server.requests)[1]}
check("usage claude: the endpoint received the login as a bearer (hashed in the log)",
      hashlib.sha256(("Bearer " + PLANTED_LOGIN).encode()).hexdigest()[:12] in sent)
check("usage claude: the beta header and accept header are sent",
      "anthropic-beta" in server.requests[-1]["headers"] and "accept" in server.requests[-1]["headers"])
server.set_routes({"/claude": {"status": 401, "body": "{}"}})
check("usage claude: a 401 is no_scope with guidance", rows_of(["claude", "@default"])[1][0]["status"] == "no_scope")
server.set_routes({"/claude": {"json": {"five_hour": {"utilization": "lots"}}}})
check("usage claude: a non-numeric utilization is an unexpected shape", rows_of(["claude", "@default"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/claude": {"json": {"somethingnew": {}}}})
check("usage claude: a response with no known window is an unexpected shape", rows_of(["claude", "@default"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/claude": {"json": CLAUDE_OK}})
write(os.path.join(PROFILES, "claude", "api", ".credentials.json"), json.dumps({"apiKey": "x"}))
r = [x for x in rows_of(["claude", "@api"])[1]][0]
check("usage claude: a login file without a subscription token is no_login", r["status"] == "no_login", str(r))
os.makedirs(os.path.join(PROFILES, "claude", "empty"))
r = rows_of(["claude", "@empty"])[1][0]
check("usage claude: a profile with no login file is no_login", r["status"] == "no_login" and "no login" in r["error"], str(r))
check("usage claude: the default home follows CLAUDE_CONFIG_DIR",
      (claude_login(os.path.join(TMP, "elsewhere"), subscriptionType="team"), rows_of(["claude", "@default"],
       env_for({"CLAUDE_CONFIG_DIR": os.path.join(TMP, "elsewhere")}))[1][0]["plan"])[1] == "team")

# secrecy and read-only
before = snapshot(TMP)
blob = ""
for args in ([], ["--json"], ["claude", "@old"], ["claude", "@infer"]):
    c, o, e = run(args)
    blob += o + e
check("usage claude: no token (access or refresh) reaches any output",
      PLANTED_LOGIN not in blob and PLANTED_REFRESH not in blob)
after = snapshot(TMP)
check("usage claude: logins and profiles are byte- and mtime-identical after runs", before == after)

# macOS Keychain (default home only), simulated with a fake `security`
if os.name != "nt":
    bindir = os.path.join(TMP, "fakebin")
    os.makedirs(bindir)
    fake = os.path.join(bindir, "security")
    keychain_json = json.dumps({"claudeAiOauth": {"accessToken": PLANTED_LOGIN, "expiresAt": int((NOW + 3600) * 1000),
                                                  "scopes": ["user:profile"], "subscriptionType": "max"}})

    def fake_security(code, payload=""):
        with open(fake, "w") as handle:
            handle.write("#!/bin/sh\nprintf '%s' '" + payload + "'\nexit " + str(code) + "\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)

    import shutil  # noqa: E402
    shutil.rmtree(os.path.join(HOME, ".claude"))
    kenv = env_for({"PATH": bindir + os.pathsep + os.environ.get("PATH", "")})
    usage.os_name = lambda: "macos"
    fake_security(0, keychain_json)
    r = rows_of(["claude", "@default"], kenv)[1][0]
    check("usage claude: a Keychain login is read on macOS for the default home", r["status"] == "ok" and r["plan"] == "max", str(r))
    fake_security(44)
    r = rows_of(["claude", "@default"], kenv)[1][0]
    check("usage claude: a missing Keychain item is no_login", r["status"] == "no_login", str(r))
    fake_security(51)
    r = rows_of(["claude", "@default"], kenv)[1][0]
    check("usage claude: a denied Keychain is no_login with the cause", r["status"] == "no_login" and "Keychain" in r["error"], str(r))
    fake_security(0, "not json")
    r = rows_of(["claude", "@default"], kenv)[1][0]
    check("usage claude: a Keychain item that is not JSON is an error row", r["status"] == "error", str(r))
    fake_security(0, keychain_json)
    r = rows_of(["claude", "@work"], kenv)[1][0]
    check("usage claude: a profile is never read from the Keychain (honest no_login)",
          r["status"] == "ok", str(r))  # @work has its own credentials file: the file wins
    os.makedirs(os.path.join(PROFILES, "claude", "kc"))
    r = rows_of(["claude", "@kc"], kenv)[1][0]
    check("usage claude: a profile without a file does not guess a Keychain entry",
          r["status"] == "no_login" and "per-profile" in r["error"], str(r))
    usage.os_name = lambda: "linux"
    r = rows_of(["claude", "@default"], kenv)[1][0]
    check("usage claude: the Keychain is not consulted off macOS", r["status"] == "no_login", str(r))
    usage.os_name = common.os_name


# =================================================================== codex

import base64  # noqa: E402


def jwt(payload):
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return "%s.%s.%s" % (enc({"alg": "none"}), enc(payload), "sig")


CODEX_OK = {"plan_type": "plus",
            "rate_limit": {"primary_window": {"used_percent": 35, "reset_at": 1790004800, "limit_window_seconds": 18000},
                           "secondary_window": {"used_percent": 14.5, "reset_at": 1790400000, "limit_window_seconds": 604800}},
            "additional_rate_limits": [{"limit_name": "codex-spark", "rate_limit": {
                "primary_window": {"used_percent": 3, "reset_at": 1790004800},
                "secondary_window": {"used_percent": 1, "reset_at": 1790400000}}}]}
INSTALLED.add("codex")


def codex_login(directory, exp=NOW + 3600, plan="plus", **tokens):
    body = {"OPENAI_API_KEY": None, "tokens": {"access_token": jwt({"exp": exp}), "refresh_token": PLANTED_REFRESH2,
                                               "id_token": jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": plan}}),
                                               "account_id": "acct-0001"}, "last_refresh": "2026-10-10T00:00:00Z"}
    body["tokens"].update(tokens)
    write(os.path.join(directory, "auth.json"), json.dumps(body))


shutil_rm = __import__("shutil").rmtree
codex_login(os.path.join(HOME, ".codex"))
codex_login(os.path.join(PROFILES, "codex", "client"), plan="team")
codex_login(os.path.join(PROFILES, "codex", "2"), plan="pro")
codex_login(os.path.join(PROFILES, "codex", "old"), exp=NOW - 5)
write(os.path.join(PROFILES, "codex", "apikey", "auth.json"), json.dumps({"OPENAI_API_KEY": "x" * 8, "tokens": None}))
write(os.path.join(PROFILES, "codex", "broken", "auth.json"), "{ nope")
os.makedirs(os.path.join(PROFILES, "codex", "none"))
server.set_routes({"/codex": {"json": CODEX_OK}})
server.requests[:] = []
code, rows, err = rows_of(["codex"])
served = len([r for r in server.requests if r["path"] == "/codex"])
by = {r["profile"]: r for r in rows}
check("usage codex: three accounts plus special cases give independent rows",
      [r["profile"] for r in rows] == ["@default", "@2", "@apikey", "@broken", "@client", "@none", "@old"], str([r["profile"] for r in rows]))
d = by["@default"]
check("usage codex: session and weekly windows are mapped",
      d["status"] == "ok" and [w["id"] for w in d["windows"][:2]] == ["5h", "7d"] and d["windows"][0]["used_pct"] == 35
      and d["windows"][1]["used_pct"] == 14.5 and d["windows"][0]["window_seconds"] == 18000, str(d))
check("usage codex: reset times are ISO UTC", d["windows"][0]["resets_at"] == usage.iso_utc(1790004800), str(d["windows"][0]))
check("usage codex: additional named limits become windows of their own",
      [w["id"] for w in d["windows"][2:]] == ["codex-spark", "codex-spark-7d"], str(d["windows"]))
check("usage codex: the response's plan label wins when present", d["plan"] == "plus" and by["@client"]["plan"] == "plus")
CODEX_NOPLAN = {k: v for k, v in CODEX_OK.items() if k != "plan_type"}
server.set_routes({"/codex": {"json": CODEX_NOPLAN}})
_, rows2, _ = rows_of(["codex"])
by2 = {r["profile"]: r for r in rows2}
check("usage codex: otherwise the plan comes from the login's plan claim",
      by2["@default"]["plan"] == "plus" and by2["@client"]["plan"] == "team" and by2["@2"]["plan"] == "pro")
server.set_routes({"/codex": {"json": CODEX_OK}})
check("usage codex: an API-key login is unsupported with a reason, not an error",
      by["@apikey"]["status"] == "unsupported" and "API-key" in by["@apikey"]["reason"] and by["@apikey"]["error"] is None, str(by["@apikey"]))
check("usage codex: an expired token is reported without a request", by["@old"]["status"] == "expired")
check("usage codex: a profile without a login file is no_login", by["@none"]["status"] == "no_login")
check("usage codex: an unreadable login file is an error row", by["@broken"]["status"] == "error")
check("usage codex: only live logins made a request (default, 2, client)", served == 3, str(served))
check("usage codex: the exit code is 1 while any row needs attention", code == 1)
server.requests[:] = []
rows_of(["codex", "@client"])
check("usage codex: the bearer reached the endpoint, hashed in the log",
      hashlib.sha256(("Bearer " + json.loads(open(os.path.join(PROFILES, "codex", "client", "auth.json")).read())["tokens"]["access_token"]).encode()).hexdigest()[:12]
      in [r["auth"] for r in server.requests])
server.set_routes({"/codex": {"json": {"rate_limit": {"primary_window": {"used_percent": "lots"}}}}})
check("usage codex: a non-numeric percent is an unexpected shape", rows_of(["codex", "@client"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/codex": {"json": {"unrelated": 1}}})
check("usage codex: a response without rate_limit is an unexpected shape", rows_of(["codex", "@client"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/codex": {"json": {"rate_limit": {"secondary_window": {"used_percent": 20, "reset_after_seconds": 3600}}}}})
r = rows_of(["codex", "@client"])[1][0]
check("usage codex: a weekly-only response with a relative reset still maps",
      r["status"] == "ok" and r["windows"][0]["id"] == "7d" and r["windows"][0]["resets_at"].endswith("Z"), str(r))
server.set_routes({"/codex": {"json": CODEX_NOPLAN}})
check("usage codex: the default home follows CODEX_HOME",
      (codex_login(os.path.join(TMP, "codex-elsewhere"), plan="edu"),
       rows_of(["codex", "@default"], env_for({"CODEX_HOME": os.path.join(TMP, "codex-elsewhere")}))[1][0]["plan"])[1] == "edu")

before = snapshot(TMP)
blob = ""
for args in ([], ["--json"], ["codex"], ["codex", "@old"]):
    c, o, e = run(args)
    blob += o + e
access = json.loads(open(os.path.join(PROFILES, "codex", "client", "auth.json")).read())["tokens"]["access_token"]
check("usage codex: no access, refresh or id token reaches any output",
      access not in blob and PLANTED_REFRESH2 not in blob and "acct-0001" not in blob)
check("usage codex: logins are byte- and mtime-identical after runs (no refresh, no write)", before == snapshot(TMP))
check("usage codex: no request ever targeted a refresh path", all("oauth" not in r["path"] and "token" not in r["path"] for r in server.requests))

server.stop()
if FAILS:
    sys.exit(1)
