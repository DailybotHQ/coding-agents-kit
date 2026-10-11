"""Bash-free checks for `ak pick` (lib/pick.py): the selection policy over
usage-v1 rows (the worked examples of the design, E1-E8, on a table shaped
like a real one), the edge cases, the grammar, and pick-v1.

    python3 tests/py/pick_checks.py            (any OS; no bash, no network)

Prints one `ok <name>` / `FAIL <name>: <why>` line per check and exits 1 when
any check failed, so the `pick` scope folds the lines in and the Windows CI
job runs it natively.
"""

import copy
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import pick  # noqa: E402
import schema_check  # noqa: E402
import usage  # noqa: E402
from common import AkError  # noqa: E402

FAILS = []
NOW = 1790000000.0
H, D, M = 3600, 86400, 60
SCHEMA = json.load(open(os.path.join(ROOT, "docs", "schema", "pick-v1.json")))


def check(name, cond, why=""):
    if cond:
        print("ok pick %s" % name)
    else:
        FAILS.append(name)
        print("FAIL pick %s: %s" % (name, why or "condition false"))


def at(seconds):
    return usage.iso_utc(NOW + seconds)


def win(wid, used, reset_in, seconds=None):
    label = {"5h": "5-hour", "7d": "7-day"}.get(wid, wid)
    if seconds is None:
        seconds = 18000 if wid.startswith("5h") else 604800
    return {"id": wid, "label": label, "used_pct": used, "resets_at": at(reset_in) if reset_in is not None else None,
            "window_seconds": seconds}


def row(cli, profile, windows, status="ok", kinds=None, **extra):
    out = {"cli": cli, "profile": profile, "kinds": kinds or [cli], "plan": None, "status": status,
           "windows": windows if status == "ok" else [], "source": "fixture", "error": None if status in ("ok", "unsupported") else status,
           "reason": None}
    out.update(extra)
    return out


# The developer's table, as usage-v1 rows (providers.toml + profile order).
CLAUDE = [
    row("claude", "@default", [win("5h", 10, H + 38 * M), win("7d", 80, D + 22 * H), win("7d-fable", 0, D + 22 * H)]),
    row("claude", "@team", [win("5h", 0, 4 * H + 8 * M), win("7d", 24, 3 * D + 3 * H), win("7d-fable", 11, 3 * D + 3 * H)]),
    row("claude", "@work1", [win("5h", 10, 38 * M), win("7d-fable", 0, H + 28 * M)]),
    row("claude", "@work2", [win("5h", 0, 3 * H + 48 * M), win("7d-fable", 0, 18 * H + 28 * M)]),
    row("claude", "@work3", [win("5h", 0, 3 * H + 58 * M), win("7d-fable", 0, 2 * D + 13 * H)]),
]
CODEX = [
    row("codex", "@default", [win("5h", 0, 4 * H + 59 * M), win("7d", 0, 6 * D + 23 * H)], resets_available=3),
    row("codex", "@work1", [win("5h", 0, H + 45 * M), win("7d", 0, 6 * D + 20 * H)], resets_available=2),
    row("codex", "@work2", [win("5h", 0, 4 * H + 59 * M), win("7d", 0, 6 * D + 23 * H)], resets_available=2),
    row("codex", "@work3", [win("5h", 0, 5 * H), win("7d", 0, 7 * D)], resets_available=2),
]
ZAI = [row("zai", "@default", [win("5h", 36, H + 51 * M), win("7d", 60, 5 * D + 3 * H)], kinds=["claude-glm", "codex-glm"])]
CURSOR = [row("cursor", "@default", [], status="unsupported", connected=True)]


def profiles_of(chosen):
    return [c["profile"] for c in chosen]


def run(rows, **kw):
    kw.setdefault("now", NOW)
    return pick.choose(copy.deepcopy(rows), **kw)


# ------------------------------------------------------- worked examples

chosen, cands, soonest = run(CLAUDE)
check("E1: ak pick claude chooses @work2 (headroom 100, profile order breaks the tie)",
      profiles_of(chosen) == ["@work2"] and chosen[0]["headroom_pct"] == 100, str(chosen))
by = {c["profile"]: c for c in cands}
check("E1: @default's binding window is the weekly one with the reserve (90 - 80 = 10)",
      by["@default"]["headroom_pct"] == 10 and by["@default"]["binding_window"] == "7d", str(by["@default"]))
check("E1: a model-only weekly window does not govern without --model", by["@work1"]["binding_window"] == "5h", str(by["@work1"]))

chosen, cands, _ = run(CLAUDE, model="fable")
check("E2: --model fable: the fable window governs, ties go to the window that resets first (@work1)",
      profiles_of(chosen) == ["@work1"] and chosen[0]["headroom_pct"] == 90, str(chosen))

chosen, _, _ = run(CLAUDE, count=3)
check("E3: --count 3 returns @work2, @work3, @work1", profiles_of(chosen) == ["@work2", "@work3", "@work1"], str(profiles_of(chosen)))

chosen, cands, _ = run(CLAUDE, needs=[("7d", 30)])
check("E4: --need 7d:30 chooses @team (only it has 30% weekly free)", profiles_of(chosen) == ["@team"], str(chosen))
check("E4: an account without a 7d window is excluded with the reason",
      any(c["profile"] == "@work2" and c["excluded_reason"] == "no 7d window" for c in cands), str(cands))

chosen, _, _ = run(ZAI)
check("E5: Z.AI: headroom 30, the 7-day window binds", chosen and chosen[0]["headroom_pct"] == 30 and chosen[0]["binding_window"] == "7d", str(chosen))

chosen, _, _ = run(CODEX)
check("E6: Codex: equal headroom, the weekly window that resets first wins (@work1)", profiles_of(chosen) == ["@work1"], str(chosen))
check("E6: resets available never count as headroom", chosen[0]["headroom_pct"] == 90, str(chosen))

chosen, cands, _ = run(CURSOR)
check("E7: a connected account with no readable quota is not chosen", chosen == [] and cands[0]["excluded_reason"].startswith("no readable quota"), str(cands))
chosen, _, _ = run(CURSOR, allow_unknown=True)
check("E7: --allow-unknown admits it with unknown headroom", profiles_of(chosen) == ["@default"] and chosen[0]["headroom_pct"] is None, str(chosen))

chosen, cands, soonest = run([CLAUDE[0]], needs=[("5h", 95)])
check("E8: --need 5h:95 on @default: none qualifies", chosen == [] and "needs 95%" in cands[0]["excluded_reason"], str(cands))
check("E8: the soonest reset is reported", soonest == at(D + 22 * H) or soonest == at(H + 38 * M), str(soonest))

# ------------------------------------------------------------- edge cases

chosen, _, _ = run(CLAUDE + CURSOR, allow_unknown=True, count=16)
check("measured accounts rank before unknown ones", profiles_of(chosen)[-1] == "@default" and chosen[-1]["cli"] == "cursor", str(profiles_of(chosen)))

bad = [row("claude", "@a", [], status="expired"), row("claude", "@b", [], status="rate_limited"),
       row("claude", "@c", [], status="no_login"), row("claude", "@d", [], status="error")]
chosen, cands, soonest = run(bad, allow_unknown=True)
check("expired, rate_limited, no_login and error accounts are never chosen (even with --allow-unknown)",
      chosen == [] and all(not c["eligible"] for c in cands), str(cands))
check("an excluded account names its status", cands[0]["excluded_reason"].startswith("expired"), str(cands[0]))
check("no measured account: soonest reset is null", soonest is None, str(soonest))

past = [row("claude", "@x", [win("5h", 100, -60), win("7d", 50, 2 * D)])]
chosen, _, _ = run(past)
check("a window whose reset is past counts as unused", chosen and chosen[0]["headroom_pct"] == 40 and chosen[0]["binding_window"] == "7d", str(chosen))

full = [row("claude", "@x", [win("5h", 100, H), win("7d", 10, 2 * D)])]
chosen, cands, _ = run(full)
check("a full window means no headroom", chosen == [] and "no headroom" in cands[0]["excluded_reason"], str(cands))

nullpct = [row("claude", "@x", [win("5h", None, H), win("7d", 10, 2 * D)])]
chosen, cands, _ = run(nullpct)
check("an unknown percent makes the headroom unknown (not chosen by default)", chosen == [] and "unknown usage" in cands[0]["excluded_reason"], str(cands))

noreset = [row("claude", "@x", [win("5h", 10, None), win("7d", 10, None)]), row("claude", "@y", [win("5h", 10, H), win("7d", 10, D)])]
chosen, _, _ = run(noreset)
check("a missing reset time ranks after a known one at equal headroom", profiles_of(chosen) == ["@y"], str(chosen))

chosen, _, _ = run(CLAUDE, exclude=["@work2", "@work3"])
check("--exclude leaves busy accounts out", profiles_of(chosen) == ["@work1"], str(chosen))

chosen, _, _ = run(CLAUDE, reserve=0)
check("--reserve 0: the weekly window may be used to the end", [c for c in run(CLAUDE, reserve=0)[1] if c["profile"] == "@default"][0]["headroom_pct"] == 20, "")

chosen, _, _ = run(CLAUDE, count=16)
check("--count larger than the qualifying accounts returns them all", len(chosen) == 5, str(len(chosen)))

chosen, cands, _ = run(CLAUDE, model="opus")
check("a --model with no scoped window falls back to the unscoped windows", profiles_of(chosen) == ["@work2"], str(chosen))

again = run(CLAUDE, count=3)
check("the decision is deterministic", again == run(CLAUDE, count=3), "")

# ----------------------------------------------------------------- grammar

opts = pick.parse_args(["claude", "@work", "--model", "fable", "--need", "5h:30", "--need", "7d-fable:20",
                        "--reserve", "15", "--count", "3", "--exclude", "@busy", "--allow-unknown", "--json", "--timeout", "5"])
check("grammar: every option parses", opts["target"] == "claude" and opts["profile"] == "@work" and opts["model"] == "fable"
      and opts["needs"] == [("5h", 30), ("7d-fable", 20)] and opts["reserve"] == 15 and opts["count"] == 3
      and opts["exclude"] == ["@busy"] and opts["allow_unknown"] and opts["json"] and opts["timeout"] == 5, str(opts))
check("grammar: @1 is @default", pick.parse_args(["claude", "@1"])["profile"] == "@default", "")
for bad_args, why in ((["--json"], "a kind is required"), (["claude", "--need", "5h"], "need without a percent"),
                      (["claude", "--need", "5h:0"], "need below 1"), (["claude", "--need", "5h:101"], "need above 100"),
                      (["claude", "--reserve", "60"], "reserve above 50"), (["claude", "--count", "0"], "count 0"),
                      (["claude", "--count", "17"], "count above 16"), (["claude", "--exclude", "work"], "exclude without @"),
                      (["claude", "--bogus"], "unknown option"), (["claude", "codex"], "two kinds"),
                      (["claude", "@a", "@b"], "two profiles"), (["claude", "--timeout", "0"], "timeout 0"),
                      (["claude", "--model"], "missing value")):
    try:
        pick.parse_args(bad_args)
        check("grammar: refuses %s" % why, False, "accepted %r" % bad_args)
    except AkError as exc:
        check("grammar: refuses %s (exit 2)" % why, exc.code == 2, str(exc.code))

# ----------------------------------------------------------------- pick-v1

for name, rows, kw in (("chosen", CLAUDE, {"count": 2}), ("none", [CLAUDE[0]], {"needs": [("5h", 95)]}),
                       ("unknown", CURSOR, {"allow_unknown": True}), ("excluded statuses", bad, {})):
    opts = pick.parse_args(["claude", "--json"] + (["--count", "2"] if kw.get("count") else []))
    opts["needs"] = list(kw.get("needs", []))
    chosen, cands, soonest = run(rows, **kw)
    doc = json.loads(pick.render_json(opts, chosen, cands, soonest, NOW))
    errors = []
    schema_check.validate(doc, SCHEMA, "$", errors)
    check("pick-v1: the %s document validates" % name, not errors, "; ".join(errors))
check("pick-v1: schema and interface", doc["schema"] == "pick-v1" and doc["interface"] == 1, str(doc))
check("pick-v1: the schema $id is pinned to a tag", "/blob/v" in SCHEMA["$id"], SCHEMA["$id"])

# ------------------------------------------------- main() over a fake fetch

class FakeModel(object):
    pass


def fake_main(args, rows):
    saved = (usage.enumerate_rows, usage.filter_rows, usage.fetch_all)
    out, err = io.StringIO(), io.StringIO()
    usage.enumerate_rows = lambda model, env: list(range(len(rows)))
    usage.filter_rows = lambda model, r, target, profile: r
    usage.fetch_all = lambda r, env, timeout, now: copy.deepcopy(rows)
    old_err, sys.stderr = sys.stderr, err
    try:
        code = pick.main(FakeModel(), args, {}, now=NOW, stdout=out)
    finally:
        sys.stderr = old_err
        usage.enumerate_rows, usage.filter_rows, usage.fetch_all = saved
    return code, out.getvalue(), err.getvalue()


code, out, err = fake_main(["claude"], CLAUDE)
check("main: exit 0 and one line naming the account", code == 0 and out.startswith("claude @work2  headroom 100%"), repr(out))
code, out, err = fake_main(["claude", "--count", "9"], CLAUDE)
check("main: fewer than --count is a warning, still exit 0", code == 0 and "only 5 of 9" in err, repr(err))
code, out, err = fake_main(["claude", "--need", "5h:95"], [CLAUDE[0]])
check("main: none qualifies exits 1 and names the soonest reset", code == 1 and out == "" and "Soonest reset" in err, repr(err))
code, out, err = fake_main(["claude", "--json"], CLAUDE)
check("main: --json prints one pick-v1 object", code == 0 and json.loads(out)["schema"] == "pick-v1", out[:80])
code, out, err = fake_main(["claude"], [])
check("main: nothing matches exits 3", code == 3, str(code))

src = open(os.path.join(ROOT, "lib", "pick.py")).read()
check("platform: lib/pick.py imports nothing POSIX-only",
      not any(t in src for t in ("import fcntl", "import pwd", "import grp", "import termios", "os.fork", "signal.alarm", "os.getuid")), "")
check("read-only: lib/pick.py opens no file and starts no process",
      "open(" not in src and "subprocess" not in src and "os.remove" not in src, "")

sys.exit(1 if FAILS else 0)
