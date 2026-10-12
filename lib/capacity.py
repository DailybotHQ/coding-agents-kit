"""`ak capacity [<kind-or-cli>] [@profile] [--self] [--model NAME] [--low PCT]
[--critical PCT] [--max-age S] [--json] [--timeout SECONDS]` — one account's
room and a verdict, cheap enough to ask at every task boundary.

- Headroom is `pick.evaluate()` with pick's defaults (reserve 10 on windows
  of 7 days or more) and pick's drill cap, so `ak capacity` and `ak pick`
  never disagree about an account.
- Verdict: `critical` when the row is rate limited or headroom <= critical;
  `low` when <= low; `ok` above; `unknown` when no headroom is readable (no
  quota source, a login problem, an error). Defaults 25 / 10;
  AGENTKIT_CAPACITY_LOW / AGENTKIT_CAPACITY_CRITICAL, then the flags, win.
- `--self` names the account this process runs on: AGENTKIT_ACTIVE_ACCOUNT
  (`<kind>/@<profile>`, set by every `ak` launch), else
  AGENTKIT_ACTIVE_PROFILE (`<cli>/<name>`), else the one CLI home variable
  that names a profile directory inside ak's own tree (CODEX_HOME=
  <profiles>/codex/work1: a Codex tool shell run by its app-server daemon).
  None of them, or several homes: exit 3, never a guess.
- The reading comes from the usage cache when fresh (lib/state.py, default
  300 s), else live (and the cache is refreshed). `ak usage` always reads
  live.

Exit: 0 for every reading (the verdict is in the output) · 2 usage or an
invalid setting · 3 unknown account / nothing matches.
"""

import json
import os
import sys

import common
import lease
import pick
import profiles
import state
import usage
from common import AkError, EXIT_OK, EXIT_NOT_READY

SCHEMA = "capacity-v1"
DEFAULT_LOW = pick.DEFAULT_LOW
DEFAULT_CRITICAL = pick.DEFAULT_CRITICAL
VERDICTS = ("ok", "low", "critical", "unknown")

USAGE = """usage: ak capacity [<kind-or-cli>] [@profile] [--self] [--model NAME] [--low PCT] [--critical PCT]
                   [--max-age S] [--json] [--timeout SECONDS]
One account's headroom and a verdict (ok, low, critical, unknown), with the
same arithmetic as ak pick. Cheap: a fresh cached reading is reused.
  --self            the account this agent runs on (set by every ak launch)
  --model NAME      model-scoped weekly windows of that model also govern
  --low PCT         low at or below PCT% headroom (default 25; AGENTKIT_CAPACITY_LOW)
  --critical PCT    critical at or below PCT% (default 10; AGENTKIT_CAPACITY_CRITICAL)
  --max-age S       reuse a cached reading up to S seconds old (default 300; 0 = live)
The usage cache holds usage numbers only; ak usage is the only command that
always reads live. AGENTKIT_CAPACITY_CAP=[<kind-or-cli>]@profile=PCT lowers a reading
(drills), never raises it.
Exit: 0 a reading (any verdict) · 2 usage · 3 unknown account or nothing matches
"""


_pct = pick._pct
thresholds = pick.thresholds      # one definition, shared with ak pick's cap rule


def verdict(status, headroom, low, critical):
    if status == "rate_limited":
        return "critical"
    if headroom is None:
        return "unknown"
    if headroom <= critical:
        return "critical"
    if headroom <= low:
        return "low"
    return "ok"


def self_account(env, model=None):
    """(kind-or-cli, @profile) of the running account, or AkError(3)."""
    marker = env.get("AGENTKIT_ACTIVE_ACCOUNT") or ""
    if "/@" in marker:
        target, label = marker.split("/@", 1)
        return target, usage._profile_label(profiles.normalize(label))
    marker = env.get("AGENTKIT_ACTIVE_PROFILE") or ""
    if "/" in marker:
        target, name = marker.split("/", 1)
        return target, usage._profile_label(profiles.normalize(name))
    found = home_accounts(env, model) if model is not None else []
    if len(found) == 1:
        return found[0]
    if found:
        raise AkError("unknown account: several CLI homes name ak profiles (%s); name one: ak capacity <kind> @profile"
                      % ", ".join("%s %s" % pair for pair in found), EXIT_NOT_READY)
    raise AkError("unknown account: this process was not launched through ak "
                  "(no AGENTKIT_ACTIVE_ACCOUNT); name one: ak capacity <kind> @profile", EXIT_NOT_READY)


def home_accounts(env, model):
    """The accounts a CLI home variable names inside ak's own profile tree:
    CODEX_HOME=<profiles>/codex/work1 is codex @work1. A process can lose the
    launch marker (Codex runs its tool shells from an app-server daemon that
    kept the environment of whoever started it) yet keep the CLI's home
    variable. Only `isolation = "env"` CLIs, only a directory that is exactly
    <profiles root>/<cli>/<name>; the CLI's default home is never derived."""
    home = env.get("AGENTKIT_REAL_HOME") or env.get("HOME") or common.home()
    root = os.path.realpath(state._profiles_root(env, home))
    found = []
    for cli_name, cli in model.clis.items():
        value = env.get(cli.get("home_env") or "") if cli.get("isolation") == "env" else None
        if not value or not os.path.isdir(value):
            continue
        parent, name = os.path.split(os.path.realpath(value))
        if parent != os.path.join(root, cli_name):
            continue
        try:
            label = usage._profile_label(profiles.normalize(name))
        except AkError:
            continue
        if label != "@default" and (cli_name, label) not in found:
            found.append((cli_name, label))
    return found


def assess(row, opts, caps, low, critical, leases, now):
    """The capacity-v1 document for one usage-v1 row (plus _source/_age)."""
    cand = pick.evaluate(row, opts["model"], pick.DEFAULT_RESERVE, (), now)
    cap = pick.apply_cap(cand, caps, low)
    headroom = cand["headroom_pct"]
    result = verdict(row["status"], headroom, low, critical)
    if cap is not None and headroom is None and result == "unknown":
        # lower-only: an unmeasured account may be marked poor, never rich
        capped = verdict(row["status"], cap, low, critical)
        if capped in ("low", "critical"):
            result = capped
    held = [r for r in leases if r["cli"] == row["cli"] and r["profile"] == row["profile"]]
    return {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": usage.iso_utc(now),
            "kind": opts["target"], "cli": row["cli"], "profile": row["profile"], "status": row["status"],
            "verdict": result, "headroom_pct": headroom, "binding_window": cand["binding_window"],
            "resets_at": cand["resets_at"], "reason": cand["excluded_reason"],
            "thresholds": {"low": low, "critical": critical}, "source": row.get("_source", "live"),
            "age_s": int(row.get("_age", 0)), "capped": cap is not None, "leases": len(held),
            "cache_note": state.CACHE_NOTE}


def parse_args(args):
    opts = {"target": None, "profile": None, "self": False, "model": None, "low": None, "critical": None,
            "max_age": state.DEFAULT_MAX_AGE, "json": False, "timeout": None}

    def value(i, flag):
        if i >= len(args):
            raise AkError("%s needs a value. See: ak capacity --help" % flag)
        return args[i]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--self":
            opts["self"] = True
        elif arg == "--model":
            i += 1
            opts["model"] = value(i, arg)
            if not pick._norm(opts["model"]):
                raise AkError("--model needs a model name (fable, opus, ...)")
        elif arg in ("--low", "--critical"):
            i += 1
            opts[arg[2:]] = _pct(value(i, arg), arg)
        elif arg == "--max-age":
            i += 1
            opts["max_age"] = pick.state_max_age(value(i, arg))
        elif arg == "--timeout":
            i += 1
            text = value(i, arg)
            if not text.isdigit() or not 1 <= int(text) <= usage.MAX_TIMEOUT:
                raise AkError("--timeout needs a number of seconds from 1 to %d" % usage.MAX_TIMEOUT)
            opts["timeout"] = int(text)
        elif arg.startswith("-"):
            raise AkError("unknown option '%s'. See: ak capacity --help" % arg)
        elif arg.startswith("@"):
            if opts["profile"] is not None:
                raise AkError("only one @profile can be given")
            opts["profile"] = usage._profile_label(profiles.normalize(arg[1:]))
        else:
            if opts["target"] is not None:
                raise AkError("only one kind or CLI can be given")
            opts["target"] = arg
        i += 1
    if opts.get("help"):
        return opts
    if opts["self"] and (opts["target"] or opts["profile"]):
        raise AkError("--self names the account itself; drop the kind and @profile")
    if not opts["self"] and opts["target"] is None:
        raise AkError("ak capacity needs a kind (ak capacity claude @work) or --self. See: ak capacity --help")
    return opts


def _line(doc, now):
    room = "unknown" if doc["headroom_pct"] is None else "%s%% free" % doc["headroom_pct"]
    text = "%s %s  %s  %s" % (doc["cli"], doc["profile"], doc["verdict"], room)
    if doc["binding_window"]:
        text += "  binding %s  resets %s" % (doc["binding_window"], usage._relative(doc["resets_at"], now))
    if doc["headroom_pct"] is None and doc["reason"]:
        text += "  (%s)" % doc["reason"]
    text += "  %s" % ("live" if doc["source"] == "live" else "cached %ds ago" % doc["age_s"])
    if doc["capped"]:
        text += "  capped"
    if doc["leases"]:
        text += "  leases %d" % doc["leases"]
    return text + "\n"


def main(model, args, env, now=None, stdout=None):
    stdout = stdout or sys.stdout
    opts = parse_args(args)
    if opts.get("help"):
        usage.emit(stdout, USAGE)
        return EXIT_OK
    low, critical = thresholds(env, opts["low"], opts["critical"])
    caps = pick.parse_caps(env, model)
    if opts["self"]:
        opts["target"], opts["profile"] = self_account(env, model)
    if opts["profile"] is None:
        opts["profile"] = "@default"
    now = usage.common_now() if now is None else now
    rows = usage.filter_rows(model, usage.enumerate_rows(model, env), opts["target"], opts["profile"])
    if not rows:
        raise AkError("unknown account: no %s account %s. Try: ak usage %s"
                      % (opts["target"], opts["profile"], opts["target"]), EXIT_NOT_READY)
    if len(rows) > 1:
        raise AkError("%s %s names %d accounts (%s); name one with its CLI or provider"
                      % (opts["target"], opts["profile"], len(rows), ", ".join("%s %s" % (r.cli, r.profile) for r in rows)))
    row = usage.fetch_cached(rows, env, opts["timeout"], now, opts["max_age"])[0]
    doc = assess(row, opts, caps, low, critical, lease.active(env, now), now)
    if opts["json"]:
        usage.emit(stdout, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    else:
        usage.emit(stdout, _line(doc, now))
    return EXIT_OK
