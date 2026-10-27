"""Bash-free checks for the Herdr resume watcher (lib/restore.py): the resume
command, when a launch starts the watcher, the secret-free watcher
environment, the report arguments, the watch loop against a scripted Herdr,
and the liveness probe on this OS. Real providers.toml model, no Herdr.

    python3 tests/py/restore_checks.py

Prints `ok <name>` / `FAIL <name>: <why>` per check; exits 1 on any failure.
"""

import json
import os
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import kinds  # noqa: E402
import last  # noqa: E402
import restore  # noqa: E402

FAILS = []


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


MODEL = kinds.load()


def prep(kind_name, profile="", auto=True):
    return types.SimpleNamespace(kind=MODEL.kind(kind_name), profile=profile, auto=auto)


HERDR = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1", "HERDR_SOCKET_PATH": "/run/herdr.sock"}

# --- the resume command --------------------------------------------------
check("the prefix names the kind and the profile", restore.argv_prefix("claude", "work", True)
      == ["ak", "claude", "@work", "--resume"], restore.argv_prefix("claude", "work", True))
check("@default is explicit", restore.argv_prefix("grok", "", True) == ["ak", "grok", "@default", "--resume"])
check("an opted-out launch resumes opted out", restore.argv_prefix("codex", "2", False)
      == ["ak", "codex", "@2", "--ask", "--resume"])
check("a provider variant keeps its kind", restore.argv_prefix("claude-glm", "x", True)[1] == "claude-glm")
check("a plain command name is valid", restore.valid_argv(["ak", "claude", "@work", "--resume", "abc-123"]))
check("a path is not a command name", not restore.valid_argv(["/usr/bin/ak", "claude"]))
check("an apostrophe is refused", not restore.valid_argv(["ak", "claude", "--resume", "it's"]))
check("a control character is refused", not restore.valid_argv(["ak", "claude", "--resume", "a\nb"]))
check("an empty argument is refused", not restore.valid_argv(["ak", ""]))

# --- when a launch starts the watcher ------------------------------------
check("inside Herdr, a CLI with a Herdr kind and a resume flag is wanted", restore.wanted(prep("claude", "work"), HERDR))
check("every Herdr-integrated CLI is covered",
      all(restore.wanted(prep(k), HERDR) for k in ("claude", "codex", "cursor", "opencode", "pi", "grok")))
check("a variant of a covered CLI is covered", restore.wanted(prep("codex-xai"), HERDR))
check("outside Herdr nothing starts", not restore.wanted(prep("claude"), {"HERDR_PANE_ID": "w1:p1"}))
check("without a pane id nothing starts", not restore.wanted(prep("claude"), {"HERDR_ENV": "1"}))
check("AGENTKIT_HERDR_RESUME=0 turns it off", not restore.wanted(prep("claude"), dict(HERDR, AGENTKIT_HERDR_RESUME="0")))
check("a CLI Herdr does not know is skipped", not restore.wanted(prep("antigravity"), HERDR))

# --- the watcher's environment carries no secret --------------------------
full = dict(HERDR, PATH="/bin", HOME="/h", XAI_API_KEY="xai-secret", CLAUDE_CODE_OAUTH_TOKEN="tok-secret",
            ANTHROPIC_AUTH_TOKEN="a-secret", CLAUDE_CONFIG_DIR="/p")
wenv = restore.watcher_env(full)
check("the watcher keeps PATH, HOME and HERDR_*", all(k in wenv for k in ("PATH", "HOME", "HERDR_ENV", "HERDR_PANE_ID",
                                                                        "HERDR_SOCKET_PATH")), sorted(wenv))
check("the watcher gets no key or token", not any("secret" in v for v in wenv.values()), sorted(wenv))
check("the watcher gets no profile home", "CLAUDE_CONFIG_DIR" not in wenv)

# --- the report ----------------------------------------------------------
SPEC = {"herdr": "herdr", "pane": "w1:p1", "agent": "claude", "pid": 1, "prefix": ["ak", "claude", "@work", "--resume"]}
sess = {"source": "herdr:claude", "agent": "claude", "kind": "id", "value": "abc-1"}
args = restore.report_args(SPEC, sess)
check("the report keeps Herdr's source and agent", args[:7] == ["pane", "report-agent-session", "w1:p1", "--source",
                                                                 "herdr:claude", "--agent", "claude"], args)
check("the report carries a numeric seq", args[7] == "--seq" and args[8].isdigit(), args)
check("the report ends with the resume command", args[args.index("--") + 1:] == ["ak", "claude", "@work", "--resume", "abc-1"],
      args)
check("another agent in the pane is not reported", restore.report_args(SPEC, dict(sess, agent="codex")) is None)
check("a path reference is not reported", restore.report_args(SPEC, dict(sess, kind="path")) is None)
check("an id Herdr would refuse is not reported", restore.report_args(SPEC, dict(sess, value="a'b")) is None)
check("a pane get answer is parsed",
      restore.pane_session(json.dumps({"result": {"pane": {"agent_session": sess}}})) == sess)
check("a pane without a session is None", restore.pane_session('{"result": {"pane": {}}}') is None)
check("garbage is None", restore.pane_session("not json") is None)


# --- the loop against a scripted Herdr ------------------------------------
def scripted(sessions, live_ticks, fail_get=False, fail_report=False):
    """A Herdr whose pane shows sessions[i] on tick i; the CLI lives for
    live_ticks reads."""
    state = {"tick": 0, "calls": []}

    def call(herdr, a):
        state["calls"].append(a)
        if a[:2] == ["pane", "get"]:
            if fail_get:
                return 1, ""
            s = sessions[min(state["tick"], len(sessions) - 1)]
            pane = {"agent_session": s} if s else {}
            return 0, json.dumps({"result": {"pane": pane}})
        return (1 if fail_report else 0), ""

    def is_alive(pid):
        return state["tick"] < live_ticks

    def sleep(_):
        state["tick"] += 1

    return state, call, is_alive, sleep


s1 = dict(sess, value="id-1")
s2 = dict(sess, value="id-2")
state, call, is_alive, sleep = scripted([None, s1, s1, s1, s2, s2], 6)
got = restore.watch(SPEC, call, is_alive, sleep, interval=0)
check("each new id is reported once, in order", got == ["id-1", "id-2"], got)
reports = [a for a in state["calls"] if a[:2] == ["pane", "report-agent-session"]]
check("a /clear (new id) moves the resume command to the new id", reports[-1][-1] == "id-2", reports)
state, call, is_alive, sleep = scripted([s1], 4, fail_report=True)
got = restore.watch(SPEC, call, is_alive, sleep, interval=0)
check("a refused report is retried on the next read", got == [] and sum(
    1 for a in state["calls"] if a[1] == "report-agent-session") == 4, state["calls"])
state, call, is_alive, sleep = scripted([dict(sess, agent="codex", value="x")], 3)
check("a pane showing another CLI is left alone", restore.watch(SPEC, call, is_alive, sleep, interval=0) == [])
state, call, is_alive, sleep = scripted([s1], 10 ** 6, fail_get=True)
restore.watch(SPEC, call, is_alive, sleep, interval=0)
check("an unreachable Herdr ends the watcher", len(state["calls"]) == restore.MAX_FAILURES, len(state["calls"]))
state, call, is_alive, sleep = scripted([s1], 0)
check("a CLI that already exited is not watched", restore.watch(SPEC, call, is_alive, sleep, interval=0) == []
      and not state["calls"])

# --- liveness on this OS --------------------------------------------------
check("this process is alive", restore.alive(os.getpid()))
done = subprocess.Popen([sys.executable, "-c", "pass"])
done.wait()
check("a finished process is not alive", not restore.alive(done.pid))

# --- ak last: the per-directory launch record -----------------------------
import tempfile  # noqa: E402

STATE = {"AGENTKIT_STATE_DIR": tempfile.mkdtemp(prefix="agentkit-last-")}
check("a launch is recorded", last.record(STATE, "claude", "work", True, directory="/a", now=100))
last.record(STATE, "grok", "", False, directory="/b", now=200)
rec = last._load(STATE)
check("the record keeps kind, profile and posture per directory",
      rec["/a"] == {"kind": "claude", "profile": "work", "ask": False, "at": 100}
      and rec["/b"] == {"kind": "grok", "profile": "default", "ask": True, "at": 200}, rec)
check("ak last continues with the same account and posture", last.command(rec["/b"]) == ["grok", "@default", "--ask", "-c"])
check("ak last -r opens the picker", last.command(rec["/a"], "-r") == ["claude", "@work", "-r"])
last.record(STATE, "codex", "2", True, directory="/a", now=300)
check("a later launch in a directory replaces its entry", last._load(STATE)["/a"]["kind"] == "codex")
for i in range(last.MAX_DIRS + 5):
    last.record(STATE, "claude", "", True, directory="/d%d" % i, now=1000 + i)
rec = last._load(STATE)
check("only the most recent directories are kept", len(rec) == last.MAX_DIRS and "/d0" not in rec
      and "/d%d" % (last.MAX_DIRS + 4) in rec, len(rec))
check("the record holds no key, id or profile path", all(set(e) == {"kind", "profile", "ask", "at"} for e in rec.values()))
if os.name != "nt":
    check("the record is private (0600)", os.stat(last._path(STATE)).st_mode & 0o777 == 0o600)
with open(last._path(STATE), "w") as handle:
    handle.write("{broken")
check("a corrupt record reads as empty", last._load(STATE) == {})
check("and is replaced by the next launch", last.record(STATE, "pi", "", True, directory="/p", now=5)
      and list(last._load(STATE)) == ["/p"])
blocked = {"AGENTKIT_STATE_DIR": os.path.join(last._path(STATE), "not-a-dir")}
check("a record that cannot be written never fails the launch", last.record(blocked, "pi", "", True) is False)

sys.exit(1 if FAILS else 0)
