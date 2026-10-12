"""Bash-free checks for `ak capacity` (lib/capacity.py), the usage cache
(lib/state.py), the drill cap and `ak lease` / `ak pick --owner`
(lib/lease.py, lib/pick.py).

    python3 tests/py/capacity_checks.py        (any OS; no bash, no network)

Every state file goes to a temporary AGENTKIT_STATE_DIR. Prints one
`ok <name>` / `FAIL <name>: <why>` line per check and exits 1 when any check
failed; the `capacity` and `lease` scopes fold the lines in and the Windows
CI job runs it natively.
"""

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import capacity  # noqa: E402
import lease  # noqa: E402
import pick  # noqa: E402
import schema_check  # noqa: E402
import state  # noqa: E402
import usage  # noqa: E402
from common import AkError  # noqa: E402

FAILS = []
NOW = 1790000000.0
H, D = 3600, 86400
TMP = tempfile.mkdtemp(prefix="ak-capacity-checks-")
ENV = {"AGENTKIT_STATE_DIR": os.path.join(TMP, "state"), "HOME": os.path.join(TMP, "home")}
PLANTED = "planted-capacity-token-0x1"


def schema(name):
    return json.load(open(os.path.join(ROOT, "docs", "schema", name)))


def check(name, cond, why=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why or "condition false"))


def raises(fn, code=None):
    try:
        fn()
    except AkError as exc:
        return code is None or exc.code == code
    return False


def win(wid, used, reset_in, seconds=None):
    if seconds is None:
        seconds = 18000 if wid.startswith("5h") else 604800
    return {"id": wid, "label": wid, "used_pct": used,
            "resets_at": usage.iso_utc(NOW + reset_in) if reset_in is not None else None, "window_seconds": seconds}


def row(cli, profile, windows, status="ok", **extra):
    out = {"cli": cli, "profile": profile, "kinds": [cli], "plan": "max", "status": status,
           "windows": windows if status == "ok" else [], "source": "fixture",
           "error": None if status in ("ok", "unsupported") else status, "reason": None}
    out.update(extra)
    return out


OPTS = {"target": "claude", "model": None}


def assess(r, low=25, critical=10, caps=(), leases=()):
    return capacity.assess(copy.deepcopy(r), OPTS, list(caps), low, critical, list(leases), NOW)


# ------------------------------------------------------------ verdicts
# 5h used 70 -> 30 free; weekly used 10 -> 90 - 10 = 80 free (reserve): headroom 30.
for used, want in ((74, "ok"), (75, "low"), (89, "low"), (90, "critical"), (100, "critical")):
    doc = assess(row("claude", "@work", [win("5h", used, H), win("7d", 10, 3 * D)]))
    check("capacity verdict: 5h at %d%% used (%s%% free) is %s" % (used, doc["headroom_pct"], want),
          doc["verdict"] == want, doc)
doc = assess(row("claude", "@work", [win("5h", 0, H), win("7d", 70, 3 * D)]))
check("capacity verdict: the weekly reserve binds (90-70 = 20 free -> low, binding 7d)",
      doc["headroom_pct"] == 20 and doc["binding_window"] == "7d" and doc["verdict"] == "low", doc)
doc = assess(row("claude", "@work", [win("5h", 95, -60), win("7d", 0, 3 * D)]))
check("capacity verdict: a window whose reset is past counts as unused", doc["verdict"] == "ok" and doc["headroom_pct"] == 90, doc)
check("capacity verdict: a rate-limited row is critical",
      assess(row("claude", "@work", [], status="rate_limited"))["verdict"] == "critical")
for status in ("unsupported", "expired", "no_login", "no_scope", "error"):
    doc = assess(row("cursor", "@default", [], status=status))
    check("capacity verdict: a %s row is unknown with a reason" % status,
          doc["verdict"] == "unknown" and doc["headroom_pct"] is None and doc["reason"], doc)
doc = assess(row("claude", "@work", [win("5h", 10, H), win("7d", None, 3 * D)]))
check("capacity verdict: unknown usage in a governing window is unknown", doc["verdict"] == "unknown", doc)
doc = assess(row("claude", "@work", [win("5h", 50, H), win("7d", 10, 3 * D)]), low=60, critical=55)
check("capacity verdict: custom thresholds apply (50 free <= 55 -> critical)", doc["verdict"] == "critical", doc)

# capacity and pick never disagree: the same rows, the same headroom.
rows = [row("claude", "@a", [win("5h", 33, H), win("7d", 41, 2 * D)]),
        row("claude", "@b", [win("5h", 2, H), win("7d", 88, 2 * D), win("7d-fable", 5, 2 * D)])]
for model in (None, "fable"):
    picked = {c["profile"]: c["headroom_pct"] for c in pick.choose(copy.deepcopy(rows), model=model, now=NOW)[1]}
    mine = {r["profile"]: capacity.assess(copy.deepcopy(r), {"target": "claude", "model": model}, [], 25, 10, [], NOW)["headroom_pct"]
            for r in rows}
    check("capacity agrees with pick on every account (model %s)" % model, picked == mine, (picked, mine))

# ---------------------------------------------------------- thresholds
check("capacity thresholds: defaults are 25 / 10", capacity.thresholds({}) == (25, 10))
check("capacity thresholds: env sets them", capacity.thresholds({"AGENTKIT_CAPACITY_LOW": "40", "AGENTKIT_CAPACITY_CRITICAL": "15"}) == (40, 15))
check("capacity thresholds: a flag wins over env",
      capacity.thresholds({"AGENTKIT_CAPACITY_LOW": "40"}, low=30) == (30, 10))
for bad in ({"AGENTKIT_CAPACITY_LOW": "x"}, {"AGENTKIT_CAPACITY_LOW": "101"}, {"AGENTKIT_CAPACITY_CRITICAL": "-1"},
            {"AGENTKIT_CAPACITY_LOW": "5", "AGENTKIT_CAPACITY_CRITICAL": "10"}):
    check("capacity thresholds: %s is a usage error" % bad, raises(lambda: capacity.thresholds(bad), 2))

# ----------------------------------------------------------------- cap
import kinds  # noqa: E402
MODEL = kinds.load()
check("capacity cap: a kind maps to the account its quota lives on (claude-glm -> zai rows)",
      pick.parse_caps({"AGENTKIT_CAPACITY_CAP": "claude-glm@work=5,claude@2=7,zai@3=1"}, MODEL)
      == [("zai", "@work", 5), ("claude", "@2", 7), ("zai", "@3", 1)])
check("capacity cap: a mistyped CLI is refused (exit 2), never a silent no-op",
      raises(lambda: pick.parse_caps({"AGENTKIT_CAPACITY_CAP": "codx@work=1"}, MODEL), 2))
check("capacity cap: entries parse, with and without a CLI",
      pick.parse_caps({"AGENTKIT_CAPACITY_CAP": "@work=5, codex@2=20,@Default=0"})
      == [(None, "@work", 5), ("codex", "@2", 20), (None, "@default", 0)])
for bad in ("work=5", "@work", "@work=101", "@work=-1", "@work=5;@x=1", "@work=five"):
    check("capacity cap: '%s' is refused (fails closed)" % bad,
          raises(lambda: pick.parse_caps({"AGENTKIT_CAPACITY_CAP": bad}), 2))
rich = row("claude", "@work", [win("5h", 10, H), win("7d", 10, 3 * D)])          # 80 free
doc = assess(rich, caps=[(None, "@work", 5)])
check("capacity cap: lowers headroom to the cap (80 -> 5, critical, capped)",
      doc["headroom_pct"] == 5 and doc["verdict"] == "critical" and doc["capped"] is True, doc)
doc = assess(rich, caps=[(None, "@work", 95)])
check("capacity cap: never raises headroom (cap 95 over 80 keeps 80)", doc["headroom_pct"] == 80 and doc["capped"], doc)
doc = assess(rich, caps=[("codex", "@work", 5)])
check("capacity cap: a CLI-scoped cap leaves another CLI's account alone", doc["headroom_pct"] == 80 and not doc["capped"], doc)
doc = assess(rich, caps=[(None, "@work", 30), (None, "@work", 12)])
check("capacity cap: the lowest of several caps applies", doc["headroom_pct"] == 12, doc)
doc = assess(row("cursor", "@work", [], status="unsupported"), caps=[(None, "@work", 5)])
check("capacity cap: an unmeasured account capped at 5 reads critical", doc["verdict"] == "critical" and doc["headroom_pct"] is None, doc)
doc = assess(row("cursor", "@work", [], status="unsupported"), caps=[(None, "@work", 80)])
check("capacity cap: an unmeasured account capped high stays unknown (never ok)", doc["verdict"] == "unknown", doc)
chosen, cands, _ = pick.choose([copy.deepcopy(rich), row("claude", "@b", [win("5h", 50, H), win("7d", 10, 3 * D)])],
                               now=NOW, caps=[(None, "@work", 5)])
check("capacity cap: pick sees the same capped headroom and ranks the capped account last",
      [c["profile"] for c in chosen] == ["@b"] and cands[1]["headroom_pct"] == 5 and cands[1]["capped"] is True, cands)
chosen, cands, _ = pick.choose([copy.deepcopy(rich)], now=NOW, caps=[(None, "@work", 0)])
check("capacity cap: a cap of 0 makes the account ineligible in pick", not chosen and cands[0]["excluded_reason"], cands)
chosen, _, _ = pick.choose([row("cursor", "@work", [], status="unsupported", connected=True)], now=NOW,
                           allow_unknown=True, caps=[(None, "@work", 5)])
check("capacity cap: --allow-unknown never chooses an unmeasured account capped low", not chosen, chosen)
for low, want in ((40, []), (25, ["@work"])):
    chosen, _, _ = pick.choose([row("cursor", "@work", [], status="unsupported", connected=True)], now=NOW,
                               allow_unknown=True, caps=[(None, "@work", 30)], low=low)
    check("capacity cap: pick marks a capped unmeasured account poor at the same low threshold as capacity (low %d)" % low,
          [c["profile"] for c in chosen] == want, chosen)
doc = assess(row("cursor", "@work", [], status="unsupported"), low=40, caps=[(None, "@work", 30)])
check("capacity cap: ... and capacity agrees (low 40, cap 30 -> low)", doc["verdict"] == "low", doc)
chosen, cands, _ = pick.choose([copy.deepcopy(rich)], now=NOW, needs=[("5h", 50)], caps=[(None, "@work", 5)])
check("capacity cap: a capped account no longer meets --need (cap 5 < need 50)",
      not chosen and "capped at 5%" in (cands[0]["excluded_reason"] or ""), cands)
chosen, _, _ = pick.choose([copy.deepcopy(rich)], now=NOW, needs=[("5h", 50)], caps=[(None, "@work", 60)])
check("capacity cap: a cap above the need keeps the account", [c["profile"] for c in chosen] == ["@work"], chosen)

# ------------------------------------------------------------- --self
check("capacity self: AGENTKIT_ACTIVE_ACCOUNT names kind and profile",
      capacity.self_account({"AGENTKIT_ACTIVE_ACCOUNT": "glm/@work"}) == ("glm", "@work"))
check("capacity self: @default is resolved", capacity.self_account({"AGENTKIT_ACTIVE_ACCOUNT": "codex/@default"}) == ("codex", "@default"))
check("capacity self: AGENTKIT_ACTIVE_PROFILE (v0.5 launches) still works",
      capacity.self_account({"AGENTKIT_ACTIVE_PROFILE": "claude/work1"}) == ("claude", "@work1"))
check("capacity self: the account marker wins over the profile marker",
      capacity.self_account({"AGENTKIT_ACTIVE_ACCOUNT": "codex/@2", "AGENTKIT_ACTIVE_PROFILE": "claude/work1"}) == ("codex", "@2"))
check("capacity self: no marker is exit 3 (unknown account, never a guess)", raises(lambda: capacity.self_account({}), 3))
check("capacity self: a malformed marker is exit 3", raises(lambda: capacity.self_account({"AGENTKIT_ACTIVE_ACCOUNT": "claude"}), 3))
check("capacity grammar: --self with a kind is a usage error", raises(lambda: capacity.parse_args(["--self", "claude"]), 2))
check("capacity grammar: no kind and no --self is a usage error", raises(lambda: capacity.parse_args([]), 2))
check("capacity grammar: an unknown option is a usage error", raises(lambda: capacity.parse_args(["claude", "--bogus"]), 2))
check("capacity grammar: --max-age takes 0..86400",
      capacity.parse_args(["claude", "--max-age", "0"])["max_age"] == 0 and raises(lambda: capacity.parse_args(["claude", "--max-age", "x"]), 2))

# --------------------------------------------------------------- cache
CACHE = os.path.join(ENV["AGENTKIT_STATE_DIR"], "usage-cache")
good = row("claude", "@work", [win("5h", 10, H), win("7d", 10, 3 * D)], token=PLANTED, _short="note", resets_available=2)
check("cache: an ok row is written", state.cache_put(ENV, good, NOW) and os.path.isfile(os.path.join(CACHE, "claude@work.json")))
blob = open(os.path.join(CACHE, "claude@work.json")).read()
check("cache: only whitelisted usage keys reach the file (a planted token never does)",
      PLANTED not in blob and "_short" not in blob and '"token"' not in blob and '"used_pct"' in blob, blob)
if os.name == "posix":
    check("cache: the file is 0600, the cache and state directories 0700",
          os.stat(os.path.join(CACHE, "claude@work.json")).st_mode & 0o777 == 0o600
          and os.stat(CACHE).st_mode & 0o777 == 0o700 and os.stat(ENV["AGENTKIT_STATE_DIR"]).st_mode & 0o777 == 0o700)
got, age = state.cache_get(ENV, "claude", "@work", NOW + 42, 300)
check("cache: a fresh entry is returned with its age", got is not None and age == 42 and got["windows"] == good["windows"], (got, age))
check("cache: an entry older than max-age is a miss", state.cache_get(ENV, "claude", "@work", NOW + 301, 300) == (None, None))
check("cache: max-age 0 always misses", state.cache_get(ENV, "claude", "@work", NOW, 0) == (None, None))
check("cache: a future-dated entry is a miss", state.cache_get(ENV, "claude", "@work", NOW - 5, 300) == (None, None))
check("cache: another account is a miss", state.cache_get(ENV, "claude", "@other", NOW, 300) == (None, None))
for status in ("no_login", "expired", "no_scope", "unsupported", "error"):
    check("cache: a %s row is not cached" % status, not state.cache_put(ENV, row("claude", "@x", [], status=status), NOW))
check("cache: a rate_limited row is cached", state.cache_put(ENV, row("claude", "@rl", [], status="rate_limited"), NOW))
with open(os.path.join(CACHE, "claude@bad.json"), "w") as handle:
    handle.write("{not json")
check("cache: a corrupt file is a miss", state.cache_get(ENV, "claude", "@bad", NOW, 300) == (None, None))
with open(os.path.join(CACHE, "claude@lie.json"), "w") as handle:
    json.dump({"schema": state.CACHE_SCHEMA, "cached_at": int(NOW), "row": dict(good, profile="@other")}, handle)
check("cache: an entry naming another account is a miss", state.cache_get(ENV, "claude", "@lie", NOW, 300) == (None, None))
check("cache: the state dir follows AGENTKIT_STATE_DIR, then XDG_STATE_HOME, then the real home",
      state.root({"AGENTKIT_STATE_DIR": "/s"}) == "/s"
      and state.root({"XDG_STATE_HOME": "/x", "HOME": "/h"}) == os.path.join("/x", "agentkit")
      and state.root({"HOME": "/fake", "AGENTKIT_REAL_HOME": "/real"}) == os.path.join("/real", ".local", "state", "agentkit"))
check("cache: an XDG_STATE_HOME inside the profiles tree (an ak env of an xdg kind) never moves the kit state",
      state.root({"HOME": "/h", "XDG_STATE_HOME": "/h/.local/share/agentkit/profiles/opencode/x/state"})
      == os.path.join("/h", ".local", "state", "agentkit")
      and state.root({"HOME": "/h", "AGENTKIT_PROFILES_DIR": "/p", "XDG_STATE_HOME": "/p/opencode/x/state"})
      == os.path.join("/h", ".local", "state", "agentkit"))


class FakeRow(object):
    def __init__(self, cli, profile):
        self.cli, self.profile = cli, profile


calls = []
saved = usage.fetch_all
usage.fetch_all = lambda rows, env, timeout, now: [calls.append(r.profile) or row(r.cli, r.profile, [win("5h", 20, H)]) for r in rows]
try:
    out = usage.fetch_cached([FakeRow("claude", "@work"), FakeRow("claude", "@new")], ENV, None, NOW + 10, 300)
    check("cache: fetch_cached answers a fresh row from the cache and fetches only the rest",
          calls == ["@new"] and out[0]["_source"] == "cache" and out[0]["_age"] == 10 and out[1]["_source"] == "live", (calls, out))
    check("cache: a live result is written back", state.cache_get(ENV, "claude", "@new", NOW + 10, 300)[0] is not None)
    del calls[:]
    usage.fetch_cached([FakeRow("claude", "@work")], ENV, None, NOW + 10, 0)
    check("cache: max-age 0 reads live", calls == ["@work"], calls)
finally:
    usage.fetch_all = saved

# --------------------------------------------------------------- leases
CODEX = ("codex", "@work", True)
CLAUDE = ("claude", "@work", False)
rec, renewed = lease.take(ENV, CODEX, "local:w1:p1", 3600, "lane cak", NOW)
check("lease: a Codex lease is created, exclusive", rec["exclusive"] and not renewed and rec["owner"] == "local:w1:p1", rec)
check("lease: a second owner on an exclusive account is refused (exit 1, names the holder)",
      raises(lambda: lease.take(ENV, CODEX, "local:w1:p2", 3600, None, NOW + 1), 1))
rec, renewed = lease.take(ENV, CODEX, "local:w1:p1", 7200, None, NOW + 10)
check("lease: the same owner renews (new expiry, purpose kept)",
      renewed and rec["expires_at"] == usage.iso_utc(NOW + 10 + 7200) and rec["purpose"] == "lane cak", rec)
lease.take(ENV, CLAUDE, "local:w1:p1", 3600, None, NOW)
lease.take(ENV, CLAUDE, "local:w1:p2", 3600, None, NOW)
check("lease: a shared account takes many owners",
      len([r for r in lease.active(ENV, NOW + 20) if r["cli"] == "claude"]) == 2)
check("lease: release by another owner removes nothing", not lease.release(ENV, CODEX, "local:w1:p2", NOW + 20)
      and any(r["cli"] == "codex" for r in lease.active(ENV, NOW + 20)))
check("lease: release by the owner frees the account", lease.release(ENV, CODEX, "local:w1:p1", NOW + 20)
      and not any(r["cli"] == "codex" for r in lease.active(ENV, NOW + 20)))
lease.take(ENV, CODEX, "local:w1:p2", 60, None, NOW + 30)
check("lease: an expired lease is ignored", not any(r["cli"] == "codex" for r in lease.active(ENV, NOW + 91)))
rec, _ = lease.take(ENV, CODEX, "local:w1:p3", 3600, None, NOW + 91)
check("lease: an expired exclusive lease no longer blocks another owner", rec["owner"] == "local:w1:p3")
store = json.load(open(os.path.join(ENV["AGENTKIT_STATE_DIR"], "leases", "leases.json")))
check("lease: expired leases are swept from the store on write",
      not any(r["owner"] == "local:w1:p2" and r["cli"] == "codex" for r in store["leases"]), store)
if os.name == "posix":
    check("lease: the store is 0600 and its directory 0700",
          os.stat(os.path.join(ENV["AGENTKIT_STATE_DIR"], "leases", "leases.json")).st_mode & 0o777 == 0o600
          and os.stat(os.path.join(ENV["AGENTKIT_STATE_DIR"], "leases")).st_mode & 0o777 == 0o700)
# Contention between processes, made deterministic: every child starts at the same instant and
# sleeps between reading the store and writing it (fault injection), so without the mutex several
# would see "no lease" and all win; with it, exactly one does.
import subprocess  # noqa: E402
RACE_ENV = {"AGENTKIT_STATE_DIR": os.path.join(TMP, "race-state"), "HOME": ENV["HOME"]}
child = os.path.join(TMP, "race_child.py")
with open(child, "w") as handle:
    handle.write("""import sys, time
sys.path.insert(0, sys.argv[1])
import lease
from common import AkError
start, owner, state_dir = float(sys.argv[2]), sys.argv[3], sys.argv[4]
real_load = lease._load
def slow_load(env):
    records = real_load(env)
    time.sleep(0.3)
    return records
lease._load = slow_load
while time.time() < start:
    time.sleep(0.005)
try:
    lease.take({"AGENTKIT_STATE_DIR": state_dir}, ("codex", "@race", True), owner, 3600, None, time.time())
    print("won")
except AkError as exc:
    print("lost %d" % exc.code)
""")
start_at = time.time() + 1.5
procs = [subprocess.Popen([sys.executable, child, os.path.join(ROOT, "lib"), str(start_at), "local:race:p%d" % i,
                           RACE_ENV["AGENTKIT_STATE_DIR"]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True) for i in range(5)]
outcomes = [p.communicate(timeout=60)[0].strip() for p in procs]
held = [r for r in lease.active(RACE_ENV, time.time()) if r["cli"] == "codex"]
check("lease race: five processes at once, exactly one gets the exclusive Codex lease",
      outcomes.count("won") == 1 and len(held) == 1, outcomes)
lock = os.path.join(ENV["AGENTKIT_STATE_DIR"], "leases", ".lock")
os.mkdir(lock)
old = time.time() - lease.LOCK_STALE - 5
os.utime(lock, (old, old))
saved_wait, lease.LOCK_WAIT = lease.LOCK_WAIT, 0.2
check("lease: a stale lock (a holder died) is broken and the write goes through",
      not raises(lambda: lease.take(ENV, ("claude", "@stale", False), "local:w1:p1", 3600, None, NOW + 100))
      and not os.path.isdir(lock) and any(r["profile"] == "@stale" for r in lease.active(ENV, NOW + 100)))
os.mkdir(lock)
check("lease: a live lock makes a writer wait, then fail (exit 70), never write unlocked",
      raises(lambda: lease.take(ENV, ("claude", "@busy", False), "local:w1:p1", 3600, None, NOW + 100), 70)
      and not any(r["profile"] == "@busy" for r in lease.active(ENV, NOW + 100)))
check("lease: a lock held by another process is never removed by a writer that gave up", os.path.isdir(lock))
os.rmdir(lock)
os.mkdir(lock)
with open(os.path.join(lock, "token"), "w") as handle:
    handle.write("someone-else")
os.utime(lock, (old, old))
check("lease: a stale lock with another holder's token is broken (renamed aside, then removed)",
      not raises(lambda: lease.take(ENV, ("claude", "@stale2", False), "local:w1:p1", 3600, None, NOW + 100))
      and not os.path.isdir(lock) and not [n for n in os.listdir(os.path.dirname(lock)) if n.startswith(".lock.stale")])
if os.name == "posix" and os.geteuid() != 0:
    os.mkdir(lock)
    os.utime(lock, (old, old))
    leases_dir = os.path.dirname(lock)
    os.chmod(leases_dir, 0o500)                                 # the stale lock cannot be renamed or removed
    started = time.time()
    try:
        check("lease: a stale lock that cannot be removed fails at the deadline instead of spinning",
              raises(lambda: lease.take(ENV, ("claude", "@pinned", False), "local:w1:p1", 3600, None, NOW + 100), 70)
              and time.time() - started < 5)
    finally:
        os.chmod(leases_dir, 0o700)
    os.rmdir(lock)
lease.LOCK_WAIT = saved_wait
lk = lease._Lock(ENV)
with lk:
    with open(os.path.join(lk.path, "token"), "w") as handle:
        handle.write("a-newer-holder")                         # the lock was broken and re-taken meanwhile
check("lease: leaving the lock never removes a lock whose token is not ours", os.path.isdir(lk.path))
shutil.rmtree(lk.path)
lk = lease._Lock(ENV)
lost = False
with lk:
    with open(os.path.join(lk.path, "token"), "w") as handle:
        handle.write("a-third-process")                        # a breaker moved our lock aside; another took it
    lost = raises(lambda: lease._save_held(lk, ENV, [], NOW), 70)
check("lease: a holder whose lock was taken over refuses to write (exit 70)", lost)
shutil.rmtree(lk.path)
aside = lk.path + ".stale-old"
os.mkdir(aside)
os.utime(aside, (old, old))
os.mkdir(lk.path)
os.utime(lk.path, (old, old))
lease.take(ENV, ("claude", "@sweep", False), "local:w1:p1", 3600, None, NOW + 100)
check("lease: breaking a stale lock also sweeps lock directories left aside long ago", not os.path.isdir(aside))
with open(os.path.join(ENV["AGENTKIT_STATE_DIR"], "leases", "leases.json"), "w") as handle:
    handle.write("garbage")
check("lease: a corrupt store reads as empty", lease.active(ENV, NOW) == [])
for bad in ("", "has space", "-dash", "x" * 81, "semi;colon"):
    check("lease: owner %r is refused" % bad, raises(lambda: lease.check_owner(bad), 2))
check("lease: pane addresses are valid owners", lease.check_owner("local:wP:pC") and lease.check_owner("box-1:w3:p1"))
for text, want in (("90m", 5400), ("4h", 14400), ("60s", 60), ("1d", 86400), ("600", 600)):
    check("lease: --ttl %s is %d seconds" % (text, want), lease.parse_ttl(text) == want)
for bad in ("59s", "25h", "2d", "h", "1w", ""):
    check("lease: --ttl %r is refused" % bad, raises(lambda: lease.parse_ttl(bad), 2))
for bad in ("token sk-abc123", "ghp_aaaaaaaaaaaaaaaaaaaa", "key=abcdef0123456789abcdef0123", "x" * 81, "line\nbreak"):
    check("lease: purpose %r is refused" % bad[:30], raises(lambda: lease.check_purpose(bad), 2))
check("lease: an ordinary purpose is kept", lease.check_purpose("T-cak capacity work, PLAN_015") == "T-cak capacity work, PLAN_015")
check("lease grammar: a lease needs --owner", raises(lambda: lease.parse_args(["codex", "@work"]), 2))
check("lease grammar: a lease needs a @profile", raises(lambda: lease.parse_args(["codex", "--owner", "a:b"]), 2))
check("lease grammar: ls takes no account", raises(lambda: lease.parse_args(["ls", "codex"]), 2))
doc = json.loads(lease.render_ls(lease.active(ENV, NOW), NOW))
errors = []
schema_check.validate(doc, schema("leases-v1.json"), "$", errors)
lease.take(ENV, CLAUDE, "local:w1:p1", 3600, "a note", NOW)
doc = json.loads(lease.render_ls(lease.active(ENV, NOW), NOW))
schema_check.validate(doc, schema("leases-v1.json"), "$", errors)
check("lease: ls --json matches docs/schema/leases-v1.json (empty and filled)", not errors and doc["leases"], errors)

# ---------------------------------------------------------- pick --owner
ROWS = [row("codex", "@a", [win("5h", 10, H), win("7d", 10, 3 * D)]),       # 80
        row("codex", "@b", [win("5h", 40, H), win("7d", 10, 3 * D)]),       # 60
        row("claude", "@c", [win("5h", 30, H), win("7d", 10, 3 * D)])]      # 70


def lrec(cli, profile, owner, exclusive):
    return {"cli": cli, "profile": profile, "owner": owner, "exclusive": exclusive, "expires_at": usage.iso_utc(NOW + H)}


LEASES = [lrec("codex", "@a", "lead-2", True), lrec("claude", "@c", "lead-2", False), lrec("claude", "@c", "lead-3", False)]
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-1")
by = {c["profile"]: c for c in cands}
check("pick owner: a Codex account leased to another owner is excluded with the holder named",
      not by["@a"]["eligible"] and "lead-2" in by["@a"]["excluded_reason"], by["@a"])
check("pick owner: rank by headroom / (1 + other leases): @b 60/1 before @c 70/3",
      [c["profile"] for c in chosen] == ["@b", "@c"] and by["@c"]["leases"] == 2, chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-2")
by = {c["profile"]: c for c in cands}
check("pick owner: the owner's own exclusive lease excludes the account too, and says how to hand it on",
      not by["@a"]["eligible"] and "(this owner)" in by["@a"]["excluded_reason"]
      and "--reuse @a" in by["@a"]["excluded_reason"], by["@a"])
check("pick owner: the owner's own leases count (@b 60/1 before @c 70/3)",
      [c["profile"] for c in chosen] == ["@b", "@c"] and by["@c"]["leases"] == 2, chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-2", reuse=["@a"])
check("pick owner: --reuse @a exempts the owner's own lease on @a only (@a 80, @b 60, @c 70/3)",
      [c["profile"] for c in chosen] == ["@a", "@b", "@c"] and {c["profile"]: c["leases"] for c in cands} == {"@a": 0, "@b": 0, "@c": 2},
      chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-2", reuse=["@c"])
check("pick owner: --reuse @c drops the owner's lease from @c's count, not another owner's (@c 70/2 = 35)",
      [c["profile"] for c in chosen] == ["@b", "@c"] and {c["profile"]: c["leases"] for c in cands}["@c"] == 1, chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-9", reuse=["@a"])
check("pick owner: --reuse never exempts another owner's exclusive lease",
      "@a" not in [c["profile"] for c in chosen], chosen)
# The drill (F4): a lead leases a lane's account under its own address, then picks for the next lane.
LANE_ROWS = [row("claude", "@work3", [win("5h", 20, H), win("7d", 10, 3 * D)]),     # 80, leased by the lead
             row("claude", "@work2", [win("5h", 50, H), win("7d", 10, 3 * D)])]     # 50, free
chosen, _, _ = pick.choose(copy.deepcopy(LANE_ROWS), now=NOW, leases=[lrec("claude", "@work3", "lead", False)], owner="lead")
check("pick owner: a lead never gets back the account it already leased to a lane (@work2 50 over @work3 80/2)",
      [c["profile"] for c in chosen] == ["@work2"], chosen)
check("pick grammar: --reuse needs --owner", raises(lambda: pick.parse_args(["codex", "--reuse", "@a"]), 2))
check("pick grammar: --reuse takes a @profile",
      raises(lambda: pick.parse_args(["codex", "--owner", "a:b", "--reuse", "a"]), 2)
      and pick.parse_args(["codex", "--owner", "a:b", "--reuse", "@A", "--reuse", "@1"])["reuse"] == ["@a", "@default"])
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES)
check("pick owner: without --owner leases are shown, not enforced (v0.5 ranking)",
      [c["profile"] for c in chosen] == ["@a", "@c", "@b"] and {c["profile"]: c["leases"] for c in cands} == {"@a": 1, "@b": 0, "@c": 2},
      chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(ROWS), count=3, now=NOW)
check("pick owner: no lease store read -> no leases key (v0.5 shape)", all("leases" not in c for c in cands))
doc = json.loads(pick.render_json({"target": "codex", "model": None, "reserve": 10, "needs": [], "count": 3, "owner": "lead-1"},
                                  *pick.choose(copy.deepcopy(ROWS), count=3, now=NOW, leases=LEASES, owner="lead-1",
                                               caps=[(None, "@b", 5)]), now=NOW))
errors = []
schema_check.validate(doc, schema("pick-v1.json"), "$", errors)
check("pick owner: pick --owner --json (leases, capped, owner) matches pick-v1", not errors, errors)

# ------------------------------------------------- unknown capacity (F2)
UNK = [row("grok", "@default", [], status="unsupported", connected=True),
       row("claude", "@low", [win("5h", 85, H), win("7d", 10, 3 * D)]),          # 15: low
       row("grok", "@gone", [], status="unsupported", connected=False)]
chosen, cands, _ = pick.choose(copy.deepcopy(UNK), count=3, now=NOW)
check("pick unknown: without --allow-unknown a no-quota account is never chosen",
      [c["profile"] for c in chosen] == ["@low"], chosen)
chosen, cands, _ = pick.choose(copy.deepcopy(UNK), count=3, now=NOW, allow_unknown=True)
check("pick unknown: --allow-unknown chooses a connected one after every measured one, verdict unknown",
      [(c["profile"], c["verdict"]) for c in chosen] == [("@low", "low"), ("@default", "unknown")], chosen)
check("pick unknown: a not-connected one stays excluded", not {c["profile"]: c for c in cands}["@gone"]["eligible"])
chosen, cands, _ = pick.choose(copy.deepcopy(UNK), count=3, now=NOW, allow_unknown=True, caps=[(None, "@default", 5)])
check("pick unknown: a capped unmeasured account reads critical (as ak capacity) and is not chosen",
      {c["profile"]: c["verdict"] for c in cands}["@default"] == "critical" and "@default" not in [c["profile"] for c in chosen],
      cands)
check("pick verdict: the same rule as ak capacity (rate limited, critical, low, ok, unknown)",
      [pick.verdict(*a) for a in (("rate_limited", 90), ("ok", 10), ("ok", 25), ("ok", 26), ("ok", None))]
      == ["critical", "critical", "low", "ok", "unknown"] and capacity.verdict is pick.verdict)


class Acct(object):
    def __init__(self, cli, profile):
        self.cli, self.profile = cli, profile


def names(rows):
    return [(r.cli, r.profile) for r in rows]


GROK = [Acct("grok", "@default"), Acct("xai", "@default")]
check("resolve: grok @default is the grok login (as ak lease always took it)",
      names([usage.account_row(MODEL, GROK, "grok", "capacity")]) == [("grok", "@default")])
check("resolve: xai @default is the xAI key", names([usage.account_row(MODEL, GROK[1:], "xai", "capacity")]) == [("xai", "@default")])
check("resolve: a provider-served kind is its provider's account (claude-glm @w -> zai @w)",
      names([usage.account_row(MODEL, [Acct("claude", "@w"), Acct("zai", "@w")], "claude-glm", "lease")]) == [("zai", "@w")])
try:
    usage.account_row(MODEL, [Acct("claude", "@w"), Acct("codex", "@w")], "claude-glm", "capacity")
    amb = None
except AkError as exc:
    amb = exc
check("resolve: a still-ambiguous pair is exit 2 naming the exact commands",
      amb is not None and amb.code == 2 and "ak capacity claude @w or ak capacity codex @w" in str(amb), amb)
check("resolve: pick offers one account per profile (grok @default, not also xai @default)",
      names(pick.one_per_profile(MODEL, [Acct("grok", "@default"), Acct("xai", "@default"), Acct("grok", "@two")], "grok"))
      == [("grok", "@default"), ("grok", "@two")])
check("resolve: pick xai keeps the xai rows", names(pick.one_per_profile(MODEL, GROK[1:], "xai")) == [("xai", "@default")])
check("resolve: pick keeps every row of a still-ambiguous profile",
      len(pick.one_per_profile(MODEL, [Acct("claude", "@w"), Acct("codex", "@w")], "claude-glm")) == 2)

# --------------------------------------------------- capacity main() end to end
out, err = io.StringIO(), io.StringIO()
saved = (usage.enumerate_rows, usage.filter_rows, usage.fetch_all)
usage.enumerate_rows = lambda model, env: [FakeRow("claude", "@work")]
usage.filter_rows = lambda model, rows, target, profile: [r for r in rows if r.profile == profile]
usage.fetch_all = lambda rows, env, timeout, now: [row("claude", "@work", [win("5h", 80, H), win("7d", 10, 3 * D)])]
old_err, sys.stderr = sys.stderr, err
try:
    env = dict(ENV, AGENTKIT_ACTIVE_ACCOUNT="claude/@work", AGENTKIT_CAPACITY_CAP="@work=8")
    code = capacity.main(None, ["--self", "--json", "--max-age", "0"], env, now=NOW, stdout=out)
    doc = json.loads(out.getvalue())
    errors = []
    schema_check.validate(doc, schema("capacity-v1.json"), "$", errors)
    check("capacity main: --self --json exits 0 and matches docs/schema/capacity-v1.json", code == 0 and not errors, errors)
    check("capacity main: the drill cap reads critical, capped, live",
          doc["verdict"] == "critical" and doc["headroom_pct"] == 8 and doc["capped"] and doc["source"] == "live", doc)
    check("capacity main: the JSON states the cache holds usage numbers only and ak usage is the only live call",
          "usage numbers only" in doc["cache_note"] and "ak usage" in doc["cache_note"])
    out.truncate(0)
    out.seek(0)
    code = capacity.main(None, ["claude", "@work", "--json"], dict(ENV), now=NOW + 5, stdout=out)
    doc = json.loads(out.getvalue())
    check("capacity main: the next reading within max-age comes from the cache",
          doc["source"] == "cache" and doc["age_s"] == 5 and doc["verdict"] == "low" and doc["headroom_pct"] == 20, doc)
    check("capacity main: an account the kit cannot see is exit 3",
          raises(lambda: capacity.main(None, ["claude", "@ghost"], dict(ENV), now=NOW, stdout=io.StringIO()), 3))
finally:
    sys.stderr = old_err
    usage.enumerate_rows, usage.filter_rows, usage.fetch_all = saved

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAILS else 0)
