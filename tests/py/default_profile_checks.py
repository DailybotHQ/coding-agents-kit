"""Bash-free checks for the per-CLI default profile: the `pick` fallback,
the `default` marks of ak usage / ak pick, and ak doctor's stranded-login
problem on Linux or in a container. Real providers.toml model, a sandbox
HOME, no network (the usage fetch is replaced), no Keychain.

    python3 tests/py/default_profile_checks.py

Prints `ok <name>` / `FAIL <name>: <why>` per check; exits 1 on any failure.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import common  # noqa: E402
import doctor  # noqa: E402
import kinds  # noqa: E402
import pick  # noqa: E402
import profiles  # noqa: E402
import usage  # noqa: E402
from common import AkError  # noqa: E402

FAILS = []
NOW = 1790000000.0
D = "AGENTKIT_DEFAULT_PROFILE_CLAUDE"


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


TMP = tempfile.mkdtemp(prefix="agentkit-default-")
HOME = os.path.join(TMP, "home")
PROFILES = os.path.join(TMP, "profiles")
os.makedirs(HOME)
os.environ["AGENTKIT_PROFILES_DIR"] = PROFILES
os.environ["HOME"] = HOME
MODEL = kinds.load()
ENV = {"HOME": HOME, "PATH": "", "AGENTKIT_KEYCHAIN": "off"}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


ACCOUNT = '{"oauthAccount":{"x":1}}'
# @default: the account file only (a Mac's Keychain login copied into Linux).
write(os.path.join(HOME, ".claude.json"), ACCOUNT)
# @work, @big: file logins (portable); @kc: the account file only.
for name in ("work", "big", "kc"):
    write(os.path.join(PROFILES, "claude", name, ".claude.json"), ACCOUNT)
for name in ("work", "big"):
    write(os.path.join(PROFILES, "claude", name, ".credentials.json"), "{}")


def row(profile, used, status="ok"):
    return {"cli": "claude", "profile": profile, "kinds": ["claude"], "plan": None, "status": status,
            "windows": [{"id": "5h", "label": "5h", "used_pct": used, "resets_at": "2099-01-01T00:00:00Z",
                         "window_seconds": 18000}] if status == "ok" else [],
            "source": "anthropic-oauth", "error": None, "reason": None}


ROWS = {"@default": row("@default", 0), "@big": row("@big", 10), "@kc": row("@kc", 0), "@work": row("@work", 60)}
asked = []


def fake_fetch(rows, env, timeout, now):
    asked.extend(r.profile for r in rows)
    return [dict(ROWS[r.profile]) for r in rows if r.profile in ROWS]


usage.fetch_all = fake_fetch
usage._installed = lambda model, env, cli_name: cli_name == "claude"
saved_os = common.os_name
common.os_name = lambda: "linux"

# --- the setting --------------------------------------------------------
check("setting: unset is None", profiles.default_setting("claude", ENV) is None)
check("setting: @work and work are the profile", profiles.default_setting("claude", dict(ENV, **{D: "@work"})) == "work"
      and profiles.default_setting("claude", dict(ENV, **{D: "work"})) == "work")
check("setting: @default is the CLI's own home", profiles.default_setting("claude", dict(ENV, **{D: "@default"})) == "")
check("setting: pick (any case) is the fallback; @pick is a profile named pick",
      profiles.default_setting("claude", dict(ENV, **{D: "PICK"})) == profiles.PICK
      and profiles.default_setting("claude", dict(ENV, **{D: "@pick"})) == "pick")
try:
    profiles.default_setting("claude", dict(ENV, **{D: "@a/b"}))
    check("setting: an invalid value is an error", False)
except AkError as exc:
    check("setting: an invalid value is an error naming the variable", D in str(exc), str(exc))
check("setting: the variable name follows the CLI", profiles.default_var("antigravity") == "AGENTKIT_DEFAULT_PROFILE_ANTIGRAVITY")

# --- pick: most headroom among portable logins --------------------------
name, room = profiles.pick_default(MODEL, "claude", ENV, now=NOW)
check("pick: the portable account with the most headroom wins", name == "big" and room == 90, "%r %r" % (name, room))
check("pick: accounts without a portable login are never asked (@default, @kc)",
      "@default" not in asked and "@kc" not in asked and set(asked) == {"@big", "@work"}, str(asked))
ROWS["@big"] = row("@big", 100)
check("pick: an account without room loses to one with room", profiles.pick_default(MODEL, "claude", ENV, now=NOW)[0] == "work")
ROWS["@work"] = row("@work", 100)
check("pick: nothing with room is None (the launch falls back to @default)",
      profiles.pick_default(MODEL, "claude", ENV, now=NOW) == (None, None))
ROWS["@big"], ROWS["@work"] = row("@big", 10), row("@work", 60)
kind = MODEL.kind("claude")
saved_warn, warned = common.warn, []
common.warn = warned.append
check("resolve: pick launches the chosen account and says so",
      profiles.resolve_default(MODEL, kind, dict(ENV, **{D: "pick"})) == ("big", D) and "chose @big" in warned[-1], str(warned))
check("resolve: a provider kind ignores the setting",
      profiles.resolve_default(MODEL, MODEL.kind("claude-glm"), dict(ENV, **{D: "@work"})) == ("", None))
common.warn = saved_warn

# --- ak usage / ak pick show it ------------------------------------------
results = [dict(r) for r in ROWS.values()]
usage.mark_defaults(MODEL, results, dict(ENV, **{D: "@work"}))
check("usage: the named default row is marked, only it", [r["profile"] for r in results if r.get("default")] == ["@work"])
results = [dict(r) for r in ROWS.values()]
usage.mark_defaults(MODEL, results, dict(ENV, **{D: "pick"}))
check("usage: under pick, the portable account ranked first is marked",
      [r["profile"] for r in results if r.get("default")] == ["@big"], str(results))
results = [dict(r) for r in ROWS.values()]
usage.mark_defaults(MODEL, results, ENV)
check("usage: without the setting nothing is marked", not any(r.get("default") for r in results))
text = usage.render_table(usage.mark_defaults(MODEL, [dict(ROWS["@work"])], dict(ENV, **{D: "@work"})),
                          usage.Platform.current(ENV, sys.stdout), False, NOW)
check("usage: the table names the default account", "@work (ak claude)" in text, text)
cands = pick.choose(usage.mark_defaults(MODEL, [dict(r) for r in ROWS.values()], dict(ENV, **{D: "@work"})), now=NOW)[1]
check("pick: the default candidate carries default: true",
      [c["profile"] for c in cands if c.get("default")] == ["@work"], str(cands))

# --- doctor: a login that stayed in a Keychain ---------------------------
problems = doctor._stranded_logins(MODEL, dict(ENV, PATH=""), {"claude": ["big", "kc", "work"]})
claude = [p for p in problems if p.startswith("claude ")]
check("doctor: @default with only the account file is flagged", any(p.startswith("claude @default:") for p in claude), str(claude))
check("doctor: so is a profile with only the account file", any(p.startswith("claude @kc:") for p in claude), str(claude))
check("doctor: a file login is never flagged", not any("@work" in p.split(":")[0] or "@big" in p.split(":")[0] for p in claude))
check("doctor: the fix names a portable profile for the default variable",
      "%s=@big" % D in [p for p in claude if p.startswith("claude @default:")][0], str(claude))
report = doctor.collect(MODEL, dict(ENV))
check("doctor: collect flags it on Linux", any(p.startswith("claude @default:") for p in report["problems"]), str(report["problems"]))
common.os_name = lambda: "macos"
report = doctor.collect(MODEL, dict(ENV))
check("doctor: on a Mac outside a container nothing is flagged (the Keychain is right there)",
      not any(p.startswith("claude @default:") for p in report["problems"]), str(report["problems"]))
common.os_name = saved_os

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAILS else 0)
