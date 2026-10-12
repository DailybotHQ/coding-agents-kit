"""Executable documentation for the agentkit-orchestrate skill.

The commands the skill teaches (fenced blocks whose first line is
`# test: <name>`) are extracted from SKILL.md and run, in order, in a sandbox
HOME that holds several Claude and Codex accounts shaped like a real table,
against fake CLIs (tests/fakes) and the loopback fake usage endpoint. Then the
failover and "nothing qualifies" paths the skill describes are driven with
its own commands. A drift between the words and the tool fails the suite.

    python3 tests/py/orchestrate_scenarios.py <kit-root> [--skill-dir DIR]

Prints `ok <name>` / `FAIL <name>: <why>`. POSIX only (the blocks are bash
and need git); the policy itself is covered natively on Windows by
tests/py/pick_checks.py.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time

ROOT = os.path.abspath(sys.argv[1])
HERE = os.path.join(ROOT, "tests", "py")
SKILL_DIR = os.path.join(ROOT, "skills", "agentkit-orchestrate")
if "--skill-dir" in sys.argv:
    SKILL_DIR = os.path.abspath(sys.argv[sys.argv.index("--skill-dir") + 1])
sys.path.insert(0, HERE)
from fake_usage_server import FakeUsageServer  # noqa: E402

PREFIX = "orchestrate-skill scenario: "
FAILS = []
NOW = time.time()
H, D, M = 3600, 86400, 60
PLANTED = "planted-orch-"


def check(name, cond, why=""):
    if cond:
        print("ok %s%s" % (PREFIX, name))
    else:
        FAILS.append(name)
        print("FAIL %s%s: %s" % (PREFIX, name, why or "condition false"))


def iso(offset):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + offset))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def jwt(payload):
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return "%s.%s.%s" % (enc({"alg": "none"}), enc(payload), "sig")


def scenario_blocks():
    text = open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8").read()
    found = {}
    for _lang, body in re.findall(r"```(\w*)\n(.*?)```", text, re.S):
        lines = textwrap.dedent(body).rstrip().splitlines()
        m = re.match(r"#\s*test:\s*(\S+)", lines[0]) if lines else None
        if m:
            found[m.group(1)] = [l for l in lines[1:] if l.strip() and not l.strip().startswith("#")]
    return found


# ----------------------------------------------------------- the sandbox

base = tempfile.mkdtemp(prefix="agentkit-orch-")
home = os.path.join(base, "home")
work = os.path.join(base, "work")
repo = os.path.join(work, "repo")
profiles = os.path.join(home, ".local", "share", "agentkit", "profiles")
fake_log = os.path.join(base, "fake.log")
os.makedirs(repo)

# Claude: the developer's table (Max default, a Team seat with a global weekly
# cap, three Team seats with model-only weekly windows).
CLAUDE = {
    "default": {"five_hour": (10, H + 38 * M), "seven_day": (80, D + 22 * H), "fable": (0, D + 22 * H)},
    "team": {"five_hour": (0, 4 * H + 8 * M), "seven_day": (24, 3 * D + 3 * H), "fable": (11, 3 * D + 3 * H)},
    "work1": {"five_hour": (10, 38 * M), "fable": (0, H + 28 * M)},
    "work2": {"five_hour": (0, 3 * H + 48 * M), "fable": (0, 18 * H + 28 * M)},
    "work3": {"five_hour": (0, 3 * H + 58 * M), "fable": (0, 2 * D + 13 * H)},
}
CODEX = {"default": 6 * D + 23 * H, "work1": 6 * D + 20 * H, "work2": 6 * D + 23 * H, "work3": 7 * D}


def claude_route(spec):
    doc = {}
    for key in ("five_hour", "seven_day"):
        if key in spec:
            doc[key] = {"utilization": spec[key][0], "resets_at": iso(spec[key][1])}
    doc["limits"] = [{"group": "weekly", "percent": spec["fable"][0], "resets_at": iso(spec["fable"][1]),
                      "scope": {"model": {"display_name": "Fable"}}}]
    return {"json": doc}


def full_route(_spec):
    return {"json": {"five_hour": {"utilization": 100, "resets_at": iso(2 * H)},
                     "seven_day": {"utilization": 100, "resets_at": iso(3 * D)}}}


claude_tokens, codex_tokens = {}, {}
for name in CLAUDE:
    directory = os.path.join(home, ".claude") if name == "default" else os.path.join(profiles, "claude", name)
    account = home if name == "default" else directory
    token = PLANTED + "claude-" + name
    claude_tokens[name] = token
    write(os.path.join(directory, ".credentials.json"), json.dumps(
        {"claudeAiOauth": {"accessToken": token, "expiresAt": 99999999999999, "scopes": ["user:profile"],
                           "subscriptionType": "max" if name == "default" else "team"}}))
    write(os.path.join(account, ".claude.json"), json.dumps({"oauthAccount": {"present": True}}))
for name, reset in CODEX.items():
    directory = os.path.join(home, ".codex") if name == "default" else os.path.join(profiles, "codex", name)
    token = jwt({"exp": NOW + 3600, "n": PLANTED + "codex-" + name})
    codex_tokens[name] = token
    write(os.path.join(directory, "auth.json"), json.dumps(
        {"OPENAI_API_KEY": None, "tokens": {"access_token": token, "refresh_token": PLANTED + "refresh",
                                             "id_token": jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "team"}}),
                                             "account_id": "acct-0001"}}))


def codex_route(name):
    limits = {"primary_window": {"used_percent": 0, "reset_at": int(NOW + 4 * H), "limit_window_seconds": 18000},
              "secondary_window": {"used_percent": 0, "reset_at": int(NOW + CODEX[name]), "limit_window_seconds": 604800}}
    return {"json": {"plan_type": "team", "rate_limit": limits}}


def routes(claude_shape=claude_route):
    codex = {"by_bearer": {tok: codex_route(n) for n, tok in codex_tokens.items()}}
    return {"/claude": {"by_bearer": {tok: claude_shape(CLAUDE[n]) for n, tok in claude_tokens.items()}}, "/codex": codex}


server = FakeUsageServer(routes=routes())
server.start()

fakes_bin = os.path.join(base, "bin")
os.makedirs(fakes_bin)
for cli in ("claude", "codex"):
    shutil.copy2(os.path.join(ROOT, "tests", "fakes", cli), os.path.join(fakes_bin, cli))
shutil.copy2(os.path.join(ROOT, "tests", "fakes", "_fake.sh"), os.path.join(fakes_bin, "_fake.sh"))

ENV = {"HOME": home, "PATH": os.pathsep.join([os.path.join(ROOT, "bin"), fakes_bin, "/usr/bin", "/bin", "/usr/local/bin"]),
       "AGENTKIT_KEYCHAIN": "off", "FAKE_MODE": "headless", "FAKE_LOG": fake_log,
       "AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH": server.base + "/claude",
       "AGENTKIT_USAGE_URL_CHATGPT_WHAM": server.base + "/codex",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.invalid", "LANG": "C.UTF-8"}
for py in ("python3",):
    exe = shutil.which(py)
    if exe:
        ENV["PATH"] += os.pathsep + os.path.dirname(exe)

captured = []


def sh(script, cwd=repo):
    proc = subprocess.run(["bash", "-c", script], cwd=cwd, env=ENV, capture_output=True, text=True, timeout=120)
    captured.append(proc.stdout + proc.stderr)
    return proc


sh("git init -q && git commit -q --allow-empty -m init")
blocks = scenario_blocks()
check("the skill marks the four runnable blocks", sorted(blocks) == ["fanout", "inventory", "pick", "review"], str(sorted(blocks)))

# ------------------------------------------------------------- inventory

lines = blocks.get("inventory", [])
usage_line = [l for l in lines if l.startswith("ak usage")]
pick_line = [l for l in lines if l.startswith("ak pick")]
proc = sh(usage_line[0].split("#")[0]) if usage_line else None
try:
    rows = json.loads(proc.stdout)["rows"]
except Exception:
    rows = []
check("inventory: ak usage --json lists every Claude and Codex account",
      sorted("%s %s" % (r["cli"], r["profile"]) for r in rows if r["cli"] in ("claude", "codex") and r["status"] == "ok")
      == sorted(["claude @%s" % n for n in CLAUDE] + ["codex @%s" % n for n in CODEX]), proc.stdout[:300] + proc.stderr[:300] if proc else "")
proc = sh(pick_line[0].split("#")[0]) if pick_line else None
try:
    chosen = [c["profile"] for c in json.loads(proc.stdout)["chosen"]]
except Exception:
    chosen = []
check("inventory: ak pick claude --count 3 --json chooses @work2, @work3, @work1", chosen == ["@work2", "@work3", "@work1"],
      (proc.stdout[:300] + proc.stderr[:300]) if proc else "")
check("inventory: the accounts it uses in the fan-out are the ones pick chose",
      all(("@%s" % a) in " ".join(blocks.get("fanout", [])) for a in ("work2", "work3")))

# ---------------------------------------------------------------- fan-out

open(fake_log, "w").close()
proc = sh("\n".join(blocks.get("fanout", [])))
check("fanout: the block runs to the end (exit 0)", proc.returncode == 0, proc.stderr[-300:])
results = {}
for lane in ("api", "ui"):
    try:
        results[lane] = json.load(open(os.path.join(repo, "%s.json" % lane)))
    except Exception as exc:
        results[lane] = {"error": str(exc)}
for lane, wt, prof in (("api", "wt-api", "work2"), ("ui", "wt-ui", "work3")):
    env = results[lane]
    check("fanout: the %s lane returned one ak run envelope with exit 0" % lane, env.get("exit") == 0 and env.get("interface") == 1, str(env)[:200])
    check("fanout: the %s lane ran in its own worktree (%s)" % (lane, wt),
          os.path.realpath(env.get("cwd", "")) == os.path.realpath(os.path.join(work, wt)), env.get("cwd", ""))
    check("fanout: the %s lane ran on its own account (@%s)" % (lane, prof), env.get("profile") == "@%s" % prof, str(env.get("profile")))
log = open(fake_log).read()
check("fanout: each delegate saw its own profile directory",
      "CLAUDE_CONFIG_DIR=%s" % os.path.join(profiles, "claude", "work2") in log
      and "CLAUDE_CONFIG_DIR=%s" % os.path.join(profiles, "claude", "work3") in log, log[:300])
check("fanout: two worktrees on two lane branches", sh("git worktree list").stdout.count("[lane/") == 2, sh("git worktree list").stdout)

# ------------------------------------------------------------------- pick

answers = []
for line in blocks.get("pick", []):
    proc = sh(line.split("#")[0])
    answers.append((line, proc.returncode, proc.stdout.strip()))
check("pick: every taught ak pick line exits 0", all(code == 0 for _l, code, _o in answers), str([(l, c) for l, c, _o in answers if c]))
want = {"ak pick claude ": "claude @work2", "--model fable": "claude @work1", "--need 5h:30": "codex @work1",
        "--exclude @work2": "claude @work3"}
for key, expect in want.items():
    got = [o for l, _c, o in answers if key in l + " "]
    check("pick: `%s` answers %s" % (key.strip(), expect), got and got[0].startswith(expect), str(got))

# ----------------------------------------------------------------- review

proc = sh("\n".join(blocks.get("review", [])))
check("review: ak pick codex then a read-only review run both succeed", proc.returncode == 0, proc.stderr[-300:])
check("review: the reviewer is another vendor on the account pick chose (codex @work1)",
      "codex @work1" in proc.stdout and '"profile": "@work1"' in proc.stdout.replace('"profile":"@work1"', '"profile": "@work1"'),
      proc.stdout[:300])

# --------------------------------------------------------------- failover

os.remove(os.path.join(profiles, "claude", "work2", ".claude.json"))        # @work2 is no longer logged in
proc = sh('ak run claude @work2 --cwd ../wt-api --output-format json -- "retry the API lane"')
check("failover: a delegate on an account that is not logged in exits 3", proc.returncode == 3, str(proc.returncode))
proc = sh("ak pick claude --exclude @work2")
check("failover: re-picking with --exclude moves the lane to @work3", proc.returncode == 0 and proc.stdout.startswith("claude @work3"), proc.stdout)
check("failover: the documented worktree discard works",
      sh("git -C ../wt-api reset -q --hard && git worktree remove ../wt-api && git worktree add -q ../wt-api lane/api").returncode == 0, "")

# ----------------------------------------------------- nothing qualifies

server.set_routes(routes(full_route))
# The next batch starts with the taught inventory: ak usage reads live and refreshes the cache pick reuses
# (the cache still holds the earlier, roomy readings at this point).
proc = sh("ak usage --json >/dev/null; ak pick claude --count 3")
check("none: after the batch's live inventory, ak pick (cache) sees every account full and exits 1",
      proc.returncode == 1, str(proc.returncode))
check("none: and names the soonest reset", "Soonest reset" in proc.stderr, proc.stderr)
proc = sh("ak pick claude --count 3 --max-age 0")
check("none: a live ak pick (--max-age 0) agrees (exit 1)", proc.returncode == 1, str(proc.returncode))
server.set_routes(routes())

# ----------------------------------------------------------- spend report

proc = sh("ak usage claude @team --json")
try:
    wins = {w["id"]: w["used_pct"] for w in json.loads(proc.stdout)["rows"][0]["windows"]}
except Exception:
    wins = {}
check("spend: one ak usage --json after the batch reports the account's windows", wins.get("7d") == 24 and wins.get("5h") == 0, str(wins))

# ------------------------------------------------------- secrecy, cleanup

leaked = [t for t in list(claude_tokens.values()) + [PLANTED + "refresh"] if any(t in c for c in captured)]
check("secrecy: no token appears in any output", not leaked, str(leaked))
check("secrecy: the fake usage endpoint was only reached on loopback", server.base.startswith("http://127.0.0.1:"), server.base)
server.stop() if hasattr(server, "stop") else None
shutil.rmtree(base, ignore_errors=True)
sys.exit(1 if FAILS else 0)
