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
import subprocess
import sys
import tempfile
import time

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
        if os.sep + os.path.join(".local", "state", "agentkit", "usage-cache") in dirpath + os.sep:
            continue        # the kit's own usage cache (usage numbers only; checked in usage_checks.py)
        for name in sorted(files):
            p = os.path.join(dirpath, name)
            with open(p, "rb") as handle:
                out.append((p, hashlib.sha256(handle.read()).hexdigest(), os.stat(p).st_mtime))
    return out


server = FakeUsageServer().start()
URLS = {"ANTHROPIC_OAUTH": "/claude", "CHATGPT_WHAM": "/codex", "ZAI_QUOTA": "/zai"}


def env_for(extra=None):
    env = {"HOME": HOME, "USERPROFILE": HOME, "PATH": os.environ.get("PATH", ""), "AGENTKIT_KEYCHAIN": "off"}
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
# A Team plan has no global weekly cap: its weekly limits come per model, in the newer `limits` list.
CLAUDE_TEAM = {"five_hour": {"utilization": 7.0, "resets_at": "2026-10-10T17:00:00Z"}, "seven_day": None,
               "limits": [{"kind": "session", "group": "session", "percent": 7, "resets_at": "2026-10-10T17:00:00Z", "scope": None},
                          {"kind": "weekly_scoped", "group": "weekly", "percent": 31, "resets_at": "2026-10-14T00:00:00Z",
                           "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}},
                          {"kind": "weekly", "group": "weekly", "percent": None, "resets_at": None, "scope": None},
                          "not-an-object"]}
server.set_routes({"/claude": {"json": CLAUDE_TEAM}})
d = rows_of(["claude", "@default"])[1][0]
check("usage claude: per-model weekly limits from the limits list become windows (Team plans)",
      d["status"] == "ok" and [(w["id"], w["label"], w["used_pct"]) for w in d["windows"]]
      == [("5h", "5-hour", 7), ("7d-fable", "7-day Fable only", 31)] and d["windows"][1]["window_seconds"] == 604800, str(d))
server.set_routes({"/claude": {"json": {"limits": [
    {"group": "session", "percent": 12, "resets_at": "2026-10-10T17:00:00Z", "scope": None},
    {"group": "weekly", "percent": 40, "resets_at": "2026-10-14T00:00:00Z", "scope": None},
    {"group": "weekly", "percent": 55, "resets_at": "2026-10-14T00:00:00Z", "scope": {"model": {"display_name": "Fable"}}}]}}})
d = rows_of(["claude", "@default"])[1][0]
check("usage claude: 5-hour, all-models weekly and a model-only weekly are three separate windows",
      [(w["id"], w["label"], w["used_pct"]) for w in d["windows"]]
      == [("5h", "5-hour", 12), ("7d", "7-day all models", 40), ("7d-fable", "7-day Fable only", 55)], str(d))
server.set_routes({"/claude": {"json": {"limits": [{"group": "session", "percent": 12, "resets_at": "2026-10-10T17:00:00Z"}]}}})
d = rows_of(["claude", "@default"])[1][0]
check("usage claude: a response with only the limits list is read", [w["id"] for w in d["windows"]] == ["5h"], str(d))
server.set_routes({"/claude": {"json": {"five_hour": {"utilization": "lots"}}}})
check("usage claude: a non-numeric utilization is an unexpected shape", rows_of(["claude", "@default"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/claude": {"json": {"somethingnew": {}}}})
check("usage claude: a response with no known window is an unexpected shape", rows_of(["claude", "@default"])[1][0]["error"] == "unexpected response shape")
server.set_routes({"/claude": {"json": CLAUDE_OK}})
write(os.path.join(PROFILES, "claude", "api", ".credentials.json"), json.dumps({"apiKey": "x"}))
r = [x for x in rows_of(["claude", "@api"])[1]][0]
check("usage claude: a login file without a subscription token is no_login", r["status"] == "no_login", str(r))
os.makedirs(os.path.join(PROFILES, "claude", "empty"))
usage.os_name = lambda: "linux"      # never consult the real Keychain of the machine running the suite
r = rows_of(["claude", "@empty"])[1][0]
usage.os_name = common.os_name
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

    argv_log = os.path.join(TMP, "security.argv")

    def fake_security(code, payload=""):
        with open(fake, "w") as handle:
            handle.write("#!/bin/sh\nprintf '%s\\n' \"$@\" > '" + argv_log + "'\nprintf '%s' '" + payload + "'\nexit " + str(code) + "\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)

    import shutil  # noqa: E402
    shutil.rmtree(os.path.join(HOME, ".claude"))
    # The suite runs with AGENTKIT_KEYCHAIN=off; these checks opt back in, against the fake `security` only.
    kenv = env_for({"PATH": bindir + os.pathsep + os.environ.get("PATH", ""), "AGENTKIT_KEYCHAIN": "on"})
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
    with open(argv_log) as handle:
        asked = handle.read().split("\n")
    expected_service = "Claude Code-credentials-" + hashlib.sha256(
        os.path.join(PROFILES, "claude", "kc").encode("utf-8")).hexdigest()[:8]
    check("usage claude: a profile without a file reads its own Keychain entry (service + sha256 of its directory)",
          r["status"] == "ok" and expected_service in asked, "%s %s" % (r, asked))
    fake_security(44)
    r = rows_of(["claude", "@kc"], kenv)[1][0]
    check("usage claude: a profile whose Keychain entry is missing is no_login with the login command",
          r["status"] == "no_login" and r["profile"] == "@kc", str(r))
    fake_security(0, keychain_json)
    r = rows_of(["claude", "@default"], env_for({"PATH": kenv["PATH"], "AGENTKIT_KEYCHAIN": "on", "CLAUDE_CONFIG_DIR": os.path.join(TMP, "cfgdir")}))[1][0]
    with open(argv_log) as handle:
        asked = handle.read().split("\n")
    check("usage claude: a default home moved by CLAUDE_CONFIG_DIR reads that directory's Keychain entry",
          r["status"] == "ok" and "Claude Code-credentials-" + hashlib.sha256(
              os.path.join(TMP, "cfgdir").encode("utf-8")).hexdigest()[:8] in asked, "%s %s" % (r, asked))
    if os.path.exists(argv_log):
        os.remove(argv_log)
    fake_security(0, keychain_json)
    r = rows_of(["claude", "@kc"], dict(kenv, AGENTKIT_KEYCHAIN="off"))[1][0]
    check("usage claude: AGENTKIT_KEYCHAIN=off never reads a Keychain secret (security is not run)",
          r["status"] != "ok" and not os.path.exists(argv_log), "%s %s" % (r, os.path.exists(argv_log)))
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
check("usage codex: a response without reset credits has no resets_available key", "resets_available" not in d, str(d))
for credits, expected in (({"available_count": 3, "applicable_available_count": 0}, 3), ({"available_count": "3"}, None),
                          ({"available_count": -1}, None), ("odd", None)):
    server.set_routes({"/codex": {"json": dict(CODEX_OK, rate_limit_reset_credits=credits)}})
    r = rows_of(["codex", "@default"])[1][0]
    check("usage codex: reset credits %r -> resets_available %r (an odd value is absent, never an error)" % (credits, expected),
          r["status"] == "ok" and r.get("resets_available") == expected, str(r))
server.set_routes({"/codex": {"json": dict(CODEX_OK, rate_limit_reset_credits={"available_count": 3})}})
text = run(["codex", "@default"])[1]
check("usage codex: the table shows the resets under the windows", "resets" in text and "3 available" in text, text)
text = run(["codex"])[1]
check("usage codex: the /usage tip is said once, on the codex title line, not on every account",
      text.count("/usage in codex") == 1 and [l for l in text.splitlines() if "/usage in codex" in l][0].startswith("codex"), text)
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


# ===================================================================== zai

ZAI_OK = {"success": True, "data": {"planName": "GLM Coding Lite", "limits": [
    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 48, "nextResetTime": 1790004800000},
    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 12, "nextResetTime": 1790400000000},
    {"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 1000, "currentValue": 250, "remaining": 750,
     "nextResetTime": 1792000000000, "usageDetails": [{"modelCode": "search-prime", "usage": 3}]}]}}
shutil_rm(os.path.join(HOME, ".codex"), ignore_errors=True)
INSTALLED.clear()
key_default, key_two = PLANTED_PROVIDER, PLANTED_PROVIDER + "-2"
zenv = env_for({"ZAI_CODING_API_KEY": key_default, "ZAI_CODING_API_KEY_2": key_two})
server.set_routes({"/zai": {"json": ZAI_OK}})
server.requests[:] = []
code, rows, _ = rows_of(["zai"], zenv)
sent = [r["auth"] for r in server.requests if r["path"] == "/zai"]
check("usage zai: one row per key, the four glm kinds collapsed into each",
      [(r["cli"], r["profile"]) for r in rows] == [("zai", "@default"), ("zai", "@2")]
      and rows[0]["kinds"] == ["claude-glm", "codex-glm", "opencode-glm", "pi-glm"], str(rows))
check("usage zai: every profile used only its own key (hashed in the endpoint's log)",
      sorted(sent) == sorted([hashlib.sha256(("Bearer " + k).encode()).hexdigest()[:12] for k in (key_default, key_two)]))
w = rows[0]["windows"]
check("usage zai: each limit entry becomes a window with a unique id, named by its period", [x["id"] for x in w] == ["5h", "7d", "mcp"], str(w))
check("usage zai: percentage and the computed fallback are mapped", [x["used_pct"] for x in w] == [48, 12, 25], str(w))
check("usage zai: epoch-millisecond resets become ISO UTC", w[0]["resets_at"] == usage.iso_utc(1790004800), str(w[0]))
check("usage zai: the plan name is reported", rows[0]["plan"] == "GLM Coding Lite")
# The shape a GLM Coding Pro key returns: two CREDIT_LIMIT entries told apart only by unit + number.
ZAI_PRO = {"code": 200, "success": True, "data": {"level": "pro", "limits": [
    {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 12000, "currentValue": 3265, "remaining": 8734,
     "percentage": 27, "nextResetTime": 1791746615622},
    {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 60000, "currentValue": 35215, "remaining": 24784,
     "percentage": 58, "nextResetTime": 1792183685977},
    {"type": "TIME_LIMIT", "unit": 3, "number": 5, "percentage": 4},
    {"type": "CREDIT_LIMIT", "unit": 99, "number": 1, "percentage": 1}]}}
server.set_routes({"/zai": {"json": ZAI_PRO}})
r = rows_of(["zai", "@default"], zenv)[1][0]
check("usage zai: unit + number name the windows like the other CLIs (5-hour, 7-day), MCP keeps its prefix",
      [(w["id"], w["label"], w["window_seconds"]) for w in r["windows"]]
      == [("5h", "5-hour", 18000), ("7d", "7-day", 604800), ("mcp-5h", "MCP 5-hour", 18000), ("credits", "Credits", None)]
      and r["plan"] == "pro", str(r))
check("usage zai: credits used and the limit are reported for the plan windows only",
      (r["windows"][0].get("used"), r["windows"][0].get("limit"), r["windows"][0].get("unit")) == (3265, 12000, "credits")
      and "limit" not in r["windows"][2], str(r["windows"]))
text = run(["zai", "@default"], zenv)[1]
check("usage zai: the table shows the credits compactly next to the reset", "3.27K/12K" in text and "35.22K/60K" in text, text)
check("usage zai: -v names the unit", "35.22K/60K credits" in run(["zai", "@default", "-v"], zenv)[1])
check("usage zai: amounts use the vendor's K/M style", [usage._amount(v) for v in (950, 3265, 12000, 1500000)] == ["950", "3.27K", "12K", "1.5M"])
server.set_routes({"/zai": {"json": {"data": {"limits": [{"type": "TOKENS_LIMIT", "percentage": 250}]}}}})
check("usage zai: percentages are clamped to 0-100", rows_of(["zai", "@default"], zenv)[1][0]["windows"][0]["used_pct"] == 100)
server.set_routes({"/zai": {"json": {"data": {"limits": []}}}})
r = rows_of(["zai", "@default"], zenv)[1][0]
check("usage zai: an empty limits list is unsupported (reason), not 0 %",
      r["status"] == "unsupported" and "no limits" in r["reason"] and r["windows"] == [], str(r))
server.set_routes({"/zai": {"json": {"data": {"limits": [{"type": "TOKENS_LIMIT"}]}}}})
check("usage zai: limits that cannot be read are unsupported, not zero",
      rows_of(["zai", "@default"], zenv)[1][0]["status"] == "unsupported")
server.set_routes({"/zai": {"json": {"nothing": 1}}})
check("usage zai: a response without data.limits is an unexpected shape", rows_of(["zai", "@default"], zenv)[1][0]["error"] == "unexpected response shape")
server.set_routes({"/zai": {"status": 401, "body": "{}"}})
check("usage zai: a rejected key is reported without the key", rows_of(["zai", "@2"], zenv)[1][0]["status"] == "no_scope")
server.set_routes({"/zai": {"json": ZAI_OK}})
os.makedirs(os.path.join(PROFILES, "claude", "work"), exist_ok=True)
code, rows, err = rows_of(["claude-glm", "@work"], zenv)
check("usage zai: a profile without its own key has no row and never borrows the default key",
      rows == [] and code == 3 and "ZAI_CODING_API_KEY_WORK is not set" in err, "%s %s" % (code, err))
check("usage zai: a key-suffix with dashes maps to the profile name",
      [r["profile"] for r in rows_of(["zai"], env_for({"ZAI_CODING_API_KEY_CLIENT_X": key_default}))[1]] == ["@client_x"])
os.makedirs(os.path.join(PROFILES, "claude", "client-x"), exist_ok=True)
check("usage zai: ... and to an existing profile directory when there is one",
      [r["profile"] for r in rows_of(["zai"], env_for({"ZAI_CODING_API_KEY_CLIENT_X": key_default}))[1]] == ["@client-x"])
blob = ""
for args in ([], ["--json"], ["zai"], ["claude-glm"]):
    c, o, e = run(args, zenv)
    blob += o + e
check("usage zai: no key value reaches any output", key_default not in blob and key_two not in blob)
files = "".join(open(p, "rb").read().decode("latin-1") for p, _h, _m in snapshot(TMP))
check("usage zai: no key value was written anywhere", key_default not in files and key_two not in files)


# ==================================================================== grok

INSTALLED.clear()
INSTALLED.add("grok")
write(os.path.join(PROFILES, "grok", "work", "auth.json"), json.dumps({"session": "PLANTED-GROK-SESSION-01"}))
server.requests[:] = []
before = snapshot(TMP)
code, rows, _ = rows_of(["grok"])
check("usage grok: @default and every profile get a row",
      [(r["cli"], r["profile"]) for r in rows] == [("grok", "@default"), ("grok", "@work")], str(rows))
check("usage grok: the recorded decision is n/d with its reason (per-session usage only)",
      all(r["status"] == "unsupported" and "per session" in r["reason"] and r["windows"] == [] and r["error"] is None for r in rows), str(rows))
check("usage grok: an n/d row is not a problem (exit 0)", code == 0, str(code))
check("usage grok: no request is made and no credential is read for an n/d source", not server.requests)
text = run(["grok"])[1]
check("usage grok: the table shows n/d and the reason", "n/d" in text and "per-session" in text)
check("usage grok: the profile directory is unchanged", before == snapshot(TMP))
check("usage grok: nothing from the profile's login reaches the output", "PLANTED-GROK-SESSION-01" not in text + run(["--json"])[1])
INSTALLED.clear()


# ===================================================================== xai

XAI_KEY, XAI_KEY2, XAI_MGMT = "PLANTED-XAI-0011", "PLANTED-XAI-0012", "PLANTED-XAI-MANAGEMENT-0013"
xenv = env_for({"XAI_API_KEY": XAI_KEY, "XAI_API_KEY_2": XAI_KEY2, "XAI_MANAGEMENT_KEY": XAI_MGMT})
server.requests[:] = []
before = snapshot(TMP)
code, rows, _ = rows_of(["xai"], xenv)
check("usage xai: one row per key, all xai kinds collapsed into each",
      [(r["cli"], r["profile"]) for r in rows] == [("xai", "@default"), ("xai", "@2")]
      and rows[0]["kinds"] == ["cline-xai", "codex-xai", "grok", "opencode-xai", "pi-xai"], str(rows))
check("usage xai: the recorded decision is n/d (a balance needs a management key ak never asks for)",
      all(r["status"] == "unsupported" and "management key" in r["reason"] and r["source"] == "none" for r in rows), str(rows))
check("usage xai: n/d is not a problem (exit 0)", code == 0)
check("usage xai: no request is made with an inference key", not server.requests)
text = run(["--json"], xenv)[1] + run([], xenv)[1]
check("usage xai: no second credential is read or shown (a management key in the environment is ignored)",
      XAI_MGMT not in text and "XAI_MANAGEMENT_KEY" not in text)
check("usage xai: no key value reaches any output", XAI_KEY not in text and XAI_KEY2 not in text)
check("usage xai: a kind filter selects the xai rows", [r["cli"] for r in rows_of(["codex-xai"], xenv)[1]] == ["xai", "xai"])
check("usage xai: nothing was written", before == snapshot(TMP))
PLANTED_AZURE = "PLANTED-AZURE-0014"
server.requests[:] = []
az = rows_of(["azure"], env_for({"AZURE_OPENAI_API_KEY": PLANTED_AZURE}))[1]
check("usage xai: an Azure key is an n/d row with the portal pointer, never fetched",
      len(az) == 1 and az[0]["status"] == "unsupported" and "Azure portal" in az[0]["reason"] and not server.requests, str(az))


# ======================================================================= nd

shutil_rm(PROFILES, ignore_errors=True)
os.makedirs(PROFILES)
server.requests[:] = []
for cli_name, name in (("cursor", "work"), ("opencode", "2"), ("pi", "2"), ("cline", "solo"), ("opencode", "solo")):
    os.makedirs(os.path.join(PROFILES, cli_name, name))
INSTALLED.update(["cursor", "opencode", "pi", "cline"])
nd_env = env_for({"ZAI_CODING_API_KEY_2": "PLANTED-ZAI-0015", "XAI_API_KEY_2": "PLANTED-XAI-0016"})
code, rows, _ = rows_of([], nd_env)
got = {(r["cli"], r["profile"]): r for r in rows}
check("usage nd: Cursor is n/d with the web-session reason, for @default and a profile",
      all(got[("cursor", p)]["status"] == "unsupported" and "web session" in got[("cursor", p)]["reason"] for p in ("@default", "@work")), str(sorted(got)))
check("usage nd: a harness profile with a routed provider key reports through the provider, not twice",
      ("opencode", "@2") not in got and ("pi", "@2") not in got and ("zai", "@2") in got and ("xai", "@2") in got, str(sorted(got)))
check("usage nd: ... and the provider row lists the harness kinds that share it",
      "opencode-glm" in got[("zai", "@2")]["kinds"] and "pi-glm" in got[("zai", "@2")]["kinds"] and "pi-xai" in got[("xai", "@2")]["kinds"])
check("usage nd: a harness profile without any routed key is n/d with a pointer",
      got[("cline", "@solo")]["status"] == "unsupported" and "no usage source of its own" in got[("cline", "@solo")]["reason"]
      and "cline-azure" in got[("cline", "@solo")]["reason"], str(got[("cline", "@solo")]))
check("usage nd: an installed harness @default is listed once, as n/d",
      got[("opencode", "@default")]["status"] == "unsupported" and got[("pi", "@default")]["status"] == "unsupported")
check("usage nd: a CLI that is not installed and has no profile is absent",
      all(r["cli"] not in ("claude", "codex", "grok") for r in rows), str(sorted(got)))
check("usage nd: a live row next to n/d rows still exits 0, and only it made a request",
      code == 0 and {r["path"] for r in server.requests} == {"/zai"}, "%s %s" % (code, {r["path"] for r in server.requests}))
server.requests[:] = []
code2, rows2, _ = rows_of(["cursor"], env_for())
check("usage nd: only n/d rows exit 0 and nothing was requested",
      code2 == 0 and rows2 and all(r["status"] == "unsupported" for r in rows2) and not server.requests, str(code2))
check("usage nd: every n/d row has a one-line reason and no error",
      all(r["reason"] and "\n" not in r["reason"] and r["error"] is None for r in rows if r["status"] == "unsupported"))
text = run(["-v"], nd_env)[1]
check("usage nd: -v lists each n/d row with its full reason",
      text.count("n/d") == len([r for r in rows if r["status"] == "unsupported"]) and "web session" in text)
text = run([], nd_env)[1]
nd_lines = [line for line in text.splitlines() if line.startswith("n/d")]
check("usage nd: without -v the n/d rows fold into one closing line grouped by cause",
      len(nd_lines) == 1 and "cursor" in text and "cline @solo" in text and "ak usage -v" in text, text)

# Connected but not measurable: listed at the very end, in a block of its own.
INSTALLED.add("grok")
write(os.path.join(HOME, ".grok", "auth.json"), "{}")
code, rows, _ = rows_of([], nd_env)
got = {(r["cli"], r["profile"]): r for r in rows}
check("usage connected: a provider key that is set makes its n/d row connected (JSON)",
      got[("xai", "@2")].get("connected") is True, str(got[("xai", "@2")]))
check("usage connected: a CLI login found on disk makes its n/d row connected (grok auth.json)",
      got[("grok", "@default")].get("connected") is True, str(got[("grok", "@default")]))
check("usage connected: a login that cannot be told stays without the key (cursor), one that is absent is false",
      "connected" not in got[("cursor", "@default")] and got[("opencode", "@default")].get("connected") is not True,
      str(got[("cursor", "@default")]))
check("usage connected: the table-only keys never reach --json", all("_how" not in r and "_short" not in r for r in rows))
text = run([], nd_env)[1]
lines = text.splitlines()
block = lines[lines.index([l for l in lines if l.startswith("connected")][0]):]
check("usage connected: a closing block lists them with how they are connected and why there is no number",
      any("grok" in l and "logged in" in l and "per-session" in l for l in block)
      and any("xai" in l and "@2" in l and "XAI_API_KEY_2 set" in l for l in block), text)
check("usage connected: the block comes after every measured block and before the n/d line",
      lines.index(block[0]) > max(i for i, l in enumerate(lines) if l.startswith("zai"))
      and lines.index(block[0]) < [i for i, l in enumerate(lines) if l.startswith("n/d")][0], text)
check("usage connected: what is connected is not repeated in the n/d line",
      "grok" not in [l for l in lines if l.startswith("n/d")][0] and "xai" not in [l for l in lines if l.startswith("n/d")][0], text)
os.remove(os.path.join(HOME, ".grok", "auth.json"))
INSTALLED.clear()

# The Keychain probe: presence only, never the secret (-w), and never under AGENTKIT_KEYCHAIN=off.
if os.name != "nt":
    import profiles  # noqa: E402
    kbin = os.path.join(TMP, "kcbin")
    os.makedirs(kbin)
    klog = os.path.join(TMP, "kc.argv")
    with open(os.path.join(kbin, "security"), "w") as handle:
        handle.write("#!/bin/sh\nprintf '%s\\n' \"$@\" > '" + klog + "'\n[ \"$3\" = present ] && exit 0\nexit 44\n")
    os.chmod(os.path.join(kbin, "security"), 0o755)
    kenv = {"PATH": kbin, "HOME": HOME}
    saved = common.os_name
    common.os_name = lambda: "macos"
    check("usage keychain: an existing item is a login", profiles.keychain_has([{"service": "present", "account": "a"}], kenv))
    with open(klog) as handle:
        asked = handle.read().split()
    check("usage keychain: only presence is asked (no -w), with the service and account",
          asked == ["find-generic-password", "-s", "present", "-a", "a"], str(asked))
    check("usage keychain: a missing item is not a login", not profiles.keychain_has([{"service": "absent"}], kenv))
    os.remove(klog)
    check("usage keychain: AGENTKIT_KEYCHAIN=off never runs security",
          not profiles.keychain_has([{"service": "present"}], dict(kenv, AGENTKIT_KEYCHAIN="off")) and not os.path.exists(klog))
    common.os_name = lambda: "linux"
    check("usage keychain: off macOS there is no Keychain to ask", not profiles.keychain_has([{"service": "present"}], kenv))

    # Claude's login kind: `.claude.json` names the account, the token is
    # `.credentials.json` or a Keychain item (per profile: suffixed by the
    # sha256 of the profile directory). Presence only, never the secret.
    with open(os.path.join(kbin, "security"), "w") as handle:
        handle.write("#!/bin/sh\nprintf '%s\\n' \"$@\" >> '" + klog + "'\n"
                     "while IFS= read -r item; do [ \"$item\" = \"$3\" ] && exit 0; done < '"
                     + os.path.join(TMP, "kc.items") + "'\nexit 44\n")   # builtins only: PATH is this folder
    kc_items = os.path.join(TMP, "kc.items")

    def plant(*services):
        with open(kc_items, "w") as handle:
            handle.write("".join(s + "\n" for s in services))

    claude_home = os.path.join(HOME, ".claude")
    os.makedirs(claude_home, exist_ok=True)
    with open(os.path.join(HOME, ".claude.json"), "w") as handle:
        handle.write('{"oauthAccount":{"x":1}}')
    kc_dir = os.path.join(PROFILES, "claude", "kc")
    os.makedirs(kc_dir, exist_ok=True)
    with open(os.path.join(kc_dir, ".claude.json"), "w") as handle:
        handle.write('{"oauthAccount":{"x":1}}')
    kc_service = "Claude Code-credentials-" + hashlib.sha256(kc_dir.encode("utf-8")).hexdigest()[:8]
    common.os_name = lambda: "macos"
    plant("Claude Code-credentials")
    check("login kind claude: @default with the Keychain item and no token file is keychain, not file",
          profiles.login_kind(MODEL, "claude", "", kenv) == "keychain")
    plant()
    check("login kind claude: @default with neither the Keychain item nor a token file is none",
          profiles.login_kind(MODEL, "claude", "", kenv) == "none")
    plant(kc_service)
    check("login kind claude: a profile's own suffixed Keychain item is keychain",
          profiles.login_kind(MODEL, "claude", "kc", kenv) == "keychain")
    plant("Claude Code-credentials")
    check("login kind claude: @default's Keychain item never logs a profile in",
          profiles.login_kind(MODEL, "claude", "kc", kenv) == "none")
    moved = os.path.join(TMP, "moved-claude")
    os.makedirs(moved, exist_ok=True)
    plant("Claude Code-credentials-" + hashlib.sha256(moved.encode("utf-8")).hexdigest()[:8])
    check("login kind claude: a default home moved by CLAUDE_CONFIG_DIR asks its suffixed item",
          profiles.login_kind(MODEL, "claude", "", dict(kenv, CLAUDE_CONFIG_DIR=moved)) == "keychain")
    plant()
    if os.path.exists(klog):
        os.remove(klog)
    check("login kind claude: AGENTKIT_KEYCHAIN=off with only the account file is unknown, and security never runs",
          profiles.login_kind(MODEL, "claude", "", dict(kenv, AGENTKIT_KEYCHAIN="off")) == "unknown"
          and not os.path.exists(klog))
    with open(klog, "w"):
        pass
    profiles.login_kind(MODEL, "claude", "", kenv)
    with open(klog) as handle:
        asked = handle.read()
    check("login kind claude: the probe never asks for the secret (-w)", "-w" not in asked.split(), asked)
    with open(os.path.join(claude_home, ".credentials.json"), "w") as handle:
        handle.write("{}")
    check("login kind claude: a token file is a file login", profiles.login_kind(MODEL, "claude", "", kenv) == "file")
    os.remove(os.path.join(claude_home, ".credentials.json"))
    common.os_name = lambda: "linux"
    plant("Claude Code-credentials")
    check("login kind claude: on Linux the account file without a token file is none",
          profiles.login_kind(MODEL, "claude", "", kenv) == "none")
    check("login state claude: doctor still reads the account file as logged in",
          profiles.login_state(MODEL, "claude", "", kenv) is True)
    os.remove(os.path.join(HOME, ".claude.json"))
    shutil_rm(kc_dir, ignore_errors=True)
    common.os_name = saved


# ================================================================ scenario
# The layout this feature was built for: three Claude, three Codex, one
# Cursor, Grok and a Z.AI subscription (two keys), all at once.

shutil_rm(PROFILES, ignore_errors=True)
shutil_rm(os.path.join(HOME, ".claude"), ignore_errors=True)
shutil_rm(os.path.join(HOME, ".codex"), ignore_errors=True)
os.makedirs(PROFILES)
INSTALLED.clear()
INSTALLED.update(["claude", "codex", "cursor", "grok"])
LAYOUT = {  # (cli, profile name or None) -> (5h %, weekly %)
    ("claude", None): (10, 5), ("claude", "work"): (55, 20), ("claude", "2"): (91, 70),
    ("codex", None): (12, 3), ("codex", "client"): (64, 30), ("codex", "2"): (98, 88)}
by_claude, by_codex = {}, {}
for (cli_name, name), (five, week) in LAYOUT.items():
    if cli_name == "claude":
        directory = os.path.join(HOME, ".claude") if name is None else os.path.join(PROFILES, "claude", name)
        tok = "planted-claude-%s-0x1" % (name or "default")
        claude_login(directory, accessToken=tok)
        by_claude[tok] = {"json": {"five_hour": {"utilization": five, "resets_at": "2099-01-01T00:00:00Z"},
                                   "seven_day": {"utilization": week, "resets_at": "2099-01-05T00:00:00Z"}}}
    else:
        directory = os.path.join(HOME, ".codex") if name is None else os.path.join(PROFILES, "codex", name)
        tok = jwt({"exp": NOW + 3600, "sub": (name or "default")})     # distinct per account
        codex_login(directory, plan="plus", access_token=tok)
        by_codex[tok] = {"json": {"rate_limit": {"primary_window": {"used_percent": five, "reset_at": 4070908800},
                                                 "secondary_window": {"used_percent": week, "reset_at": 4071340800}}}}
os.makedirs(os.path.join(PROFILES, "cursor", "default_unused"), exist_ok=True)
shutil_rm(os.path.join(PROFILES, "cursor"), ignore_errors=True)
ZBASE, ZTWO = "planted-zai-base-0x1", "planted-zai-two-0x1"
zkeys = {"ZAI_CODING_API_KEY": ZBASE, "ZAI_CODING_API_KEY_2": ZTWO}
by_zai = {zkeys["ZAI_CODING_API_KEY"]: {"json": {"data": {"planName": "lite", "limits": [{"type": "TOKENS_LIMIT", "percentage": 48, "nextResetTime": 4070908800000}]}}},
          zkeys["ZAI_CODING_API_KEY_2"]: {"json": {"data": {"planName": "pro", "limits": [{"type": "TOKENS_LIMIT", "percentage": 77, "nextResetTime": 4070908800000}]}}}}


def scenario_routes(**patch):
    routes = {"/claude": {"by_bearer": dict(by_claude)}, "/codex": {"by_bearer": dict(by_codex)}, "/zai": {"by_bearer": dict(by_zai)}}
    for path, bearer, change in patch.get("patch", []):
        routes[path]["by_bearer"][bearer] = change
    return routes


server.set_routes(scenario_routes())
senv = env_for(zkeys)
before = snapshot(TMP)
server.requests[:] = []
code, rows, _ = rows_of([], senv)
first_run_requests = len(server.requests)
got = {(r["cli"], r["profile"]): r for r in rows}
check("usage scenario: every account of the layout has exactly one row",
      sorted(got) == sorted([("claude", "@default"), ("claude", "@work"), ("claude", "@2"), ("codex", "@default"), ("codex", "@client"),
                             ("codex", "@2"), ("cursor", "@default"), ("grok", "@default"), ("zai", "@default"), ("zai", "@2")]),
      str(sorted(got)))
mixed = []
for (cli_name, name), (five, week) in LAYOUT.items():
    label = "@" + (name or "default")
    w = got[(cli_name, label)]["windows"]
    if [w[0]["used_pct"], w[1]["used_pct"]] != [five, week]:
        mixed.append((cli_name, label, [x["used_pct"] for x in w]))
check("usage scenario: no account's numbers are mixed up with another's", not mixed, str(mixed))
check("usage scenario: Z.AI shows each key's own plan and quota",
      (got[("zai", "@default")]["plan"], got[("zai", "@default")]["windows"][0]["used_pct"]) == ("lite", 48)
      and (got[("zai", "@2")]["plan"], got[("zai", "@2")]["windows"][0]["used_pct"]) == ("pro", 77))
check("usage scenario: Cursor and Grok are n/d with their reasons",
      got[("cursor", "@default")]["status"] == "unsupported" and got[("grok", "@default")]["status"] == "unsupported")
check("usage scenario: the whole layout is healthy (exit 0)", code == 0, str(code))
text = run([], senv)[1]
check("usage scenario: the table carries every account and its numbers",
      all(tag in text for tag in ("@client", "91%", "98%", "77%", "n/d")) and text.count("\n") >= 14)
check("usage scenario: the first run made one request per live row (eight)", first_run_requests == 8, str(first_run_requests))
doc_path = os.path.join(TMP, "scenario.json")
write(doc_path, run(["--json"], senv)[1])
verdict = subprocess.run([sys.executable, os.path.join(HERE, "schema_check.py"), os.path.join(ROOT, "docs", "schema", "usage-v1.json"), doc_path],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode().strip()
check("usage scenario: --json validates against the schema", verdict == "valid", verdict)
os.remove(doc_path)
check("usage scenario: kind and profile filters work on the layout",
      [r["profile"] for r in rows_of(["codex", "@client"], senv)[1]] == ["@client"]
      and {r["cli"] for r in rows_of(["claude-glm"], senv)[1]} == {"zai"})

# partial failure: one slow, one rejected, one with a changed shape
slow_tok = [t for t in by_claude if "work" in t][0]
bad_tok = [t for t in by_codex][1]
shape_tok = [t for t in by_claude if "-2-" in t][0]
server.set_routes(scenario_routes(patch=[("/claude", slow_tok, {"delay": 3}), ("/codex", bad_tok, {"status": 401, "json": {}}),
                                         ("/claude", shape_tok, {"json": {"surprise": True}})]))
started = time.time()
code, rows, _ = rows_of(["--timeout", "1"], senv)
elapsed = time.time() - started
got = {(r["cli"], r["profile"]): r for r in rows}
statuses = {k: v["status"] for k, v in got.items()}
check("usage scenario: failures stay on their rows; healthy rows keep their numbers",
      got[("claude", "@default")]["status"] == "ok" and got[("claude", "@default")]["windows"][0]["used_pct"] == 10
      and got[("codex", "@2")]["windows"][0]["used_pct"] == 98
      and sum(1 for v in statuses.values() if v == "ok") >= 5, str(statuses))
check("usage scenario: slow, rejected and reshaped rows are reported with their own status",
      got[("claude", "@work")]["error"] == "timed out after 1s" and got[("claude", "@2")]["error"] == "unexpected response shape"
      and "no_scope" in statuses.values(), str(statuses))
check("usage scenario: partial failure exits 1 and finishes near the timeout, not the sum", code == 1 and elapsed < 3.5, "%s %.1f" % (code, elapsed))
alltext = run([], senv)[1] + run(["--json"], senv)[1]
check("usage scenario: no token or key of the layout appears in any output",
      not any(t in alltext for t in list(by_claude) + list(zkeys.values())) and "planted-zai" not in alltext)
server.set_routes(scenario_routes())
after = snapshot(TMP)
check("usage scenario: every profile directory and the env are byte-identical after all runs",
      [x[:2] for x in before] == [x[:2] for x in after] and [x[2] for x in before] == [x[2] for x in after])

server.stop()
if FAILS:
    sys.exit(1)
