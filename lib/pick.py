"""`ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT]
[--count N] [--exclude @profile]... [--allow-unknown] [--owner ADDR] [--max-age S] [--json] [--timeout SECONDS]`
— the account(s) with the most usable headroom for a kind.

It reads the same rows as `ak usage` (same enumeration, filter and parallel
fetch; no login is refreshed, no reset is spent; the only file written is the
kit's usage cache, lib/state.py, read back while fresh) and applies one
documented policy (docs/usage.md#choosing-an-account):

- only `ok` rows are eligible; `unsupported` but connected accounts only with
  --allow-unknown, ranked after every measured account;
- governing windows: every window without a model scope, plus the
  model-scoped ones (`7d-<model>`) that match --model;
- a window whose reset is past counts as unused; windows of 7 days or more
  keep --reserve percent (default 10) unused;
- headroom = the minimum free percent over the governing windows (the
  binding window gives it); --need WIN:PCT must hold for the window with
  exactly that id;
- rank: headroom, then the account whose earliest long window resets first
  ("spend what expires first"), then providers.toml and profile order;
- AGENTKIT_CAPACITY_CAP lowers a headroom to min(real, cap), never raises it
  (`cap_of`/`apply_cap`, shared with `ak capacity`);
- with --owner, an account leased exclusively (Codex) to another owner is
  excluded and the rest rank by headroom / (1 + leases held by others).

`choose()` is pure (rows in, decision out) so the policy is tested without a
network. Portable: no OS-specific code.
"""

import json
import re

import common
import lease
import profiles
import state
import usage
from common import AkError, EXIT_OK, EXIT_USAGE

SCHEMA = "pick-v1"
EXIT_NONE = 1        # no account qualifies
EXIT_NOTHING = 3     # nothing matches the filter
DEFAULT_RESERVE = 10
MAX_RESERVE = 50
MAX_COUNT = 16
LONG_SECONDS = 7 * 86400
SCOPED = re.compile(r"^(5h|7d)-(.+)$")

USAGE = """usage: ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT]
               [--count N] [--exclude @profile]... [--allow-unknown] [--json] [--timeout SECONDS]
The account(s) with the most usable headroom for a kind, from the same rows as
ak usage (read-only: no login is refreshed, no reset is spent).
  --model NAME      model-scoped weekly windows of that model also govern (fable, opus, ...)
  --need WIN:PCT    the window with id WIN (5h, 7d, 7d-fable) must keep PCT% free
  --reserve PCT     keep PCT% of every window of 7 days or more unused (default 10, max 50)
  --count N         up to N distinct accounts, best first (default 1, max 16)
  --exclude @name   leave an account out (repeatable), e.g. one already busy
  --allow-unknown   connected accounts with no readable quota may be chosen, last
  --owner ADDR      choose for this lease owner: skip Codex accounts leased to others,
                    rank by headroom / (1 + leases held by others) (see ak lease)
  --max-age S       use cached usage up to S seconds old (default 300; 0 = always live)
Exit: 0 chosen · 1 none qualifies (the soonest reset is named) · 2 usage · 3 nothing matches
"""


# ---------------------------------------------------------------- policy

def _is_long(win):
    seconds = win.get("window_seconds")
    if isinstance(seconds, int) and not isinstance(seconds, bool):
        return seconds >= LONG_SECONDS
    return win.get("id", "").startswith("7d")


def _norm(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _governs(win, model):
    match = SCOPED.match(win.get("id", ""))
    if not match:
        return True
    if not model:
        return False
    scope, wanted = set(match.group(2).split("-")), set(_norm(model).split("-"))
    return scope <= wanted or wanted <= scope      # fable ~ 7d-fable, claude-opus-4-5 ~ 7d-opus; not o ~ sonnet


def _free(win, reserve, now):
    """Free percent of one window (reserve applied), or None when unknown."""
    used = win.get("used_pct")
    resets = win.get("resets_at")
    if resets and usage.epoch_of(resets) <= now:
        used = 0
    if used is None:
        return None
    cap = 100 - reserve if _is_long(win) else 100
    return max(0.0, cap - float(used))


def _num(value):
    return int(value) if value == int(value) else round(value, 1)


def evaluate(row, model, reserve, needs, now):
    """One candidate (pick-v1) from one usage-v1 row."""
    cand = {"cli": row["cli"], "profile": row["profile"], "kinds": list(row.get("kinds", [])),
            "status": row["status"], "eligible": False, "headroom_pct": None,
            "binding_window": None, "resets_at": None, "excluded_reason": None,
            "_long_reset": None, "_unknown": False}
    if row.get("default"):
        cand["default"] = True      # the account a bare `ak <cli>` launches (additive)
    status = row["status"]
    if status == "unsupported":
        cand["_unknown"] = True
        cand["excluded_reason"] = "no readable quota" + ("" if row.get("connected") else " and not connected")
        cand["_connected"] = bool(row.get("connected"))
        return cand
    if status != "ok":
        cand["excluded_reason"] = "%s: %s" % (status, row.get("error") or status)
        return cand
    governing = [w for w in row.get("windows", []) if _governs(w, model)]
    if not governing:
        cand["_unknown"] = True
        cand["_connected"] = True
        cand["excluded_reason"] = "no window governs this kind"
        return cand
    frees = [(_free(w, reserve, now), w) for w in governing]
    longs = [w.get("resets_at") for w in governing if _is_long(w) and w.get("resets_at")]
    cand["_long_reset"] = min(longs, key=usage.epoch_of) if longs else None
    if any(f is None for f, _ in frees):
        unknown = [w["id"] for f, w in frees if f is None]
        cand["_unknown"] = True
        cand["_connected"] = True
        cand["excluded_reason"] = "unknown usage in %s" % ", ".join(unknown)
        return cand
    free, binding = min(frees, key=lambda pair: (pair[0], pair[1].get("id", "")))
    cand["headroom_pct"] = _num(free)
    cand["binding_window"] = binding.get("id")
    cand["resets_at"] = binding.get("resets_at")
    by_id = {w.get("id"): w for w in row.get("windows", [])}
    for wid, pct in needs:
        win = by_id.get(wid)
        if win is None:
            cand["excluded_reason"] = "no %s window" % wid
            return cand
        have = _free(win, reserve, now)
        if have is None or have < pct:
            cand["excluded_reason"] = "%s has %s%% free, needs %s%%" % (wid, "?" if have is None else _num(have), _num(pct))
            return cand
    if free <= 0:
        cand["excluded_reason"] = "no headroom (%s)" % binding.get("id")
        return cand
    cand["eligible"] = True
    return cand


# ------------------------------------------------------------------ cap

CAP_VAR = "AGENTKIT_CAPACITY_CAP"
CAP_ENTRY = re.compile(r"^([a-z0-9][a-z0-9-]{0,40})?(@[a-z0-9][a-z0-9._-]{0,31})=(\d{1,3})$")
UNKNOWN_CAP_LIMIT = 25      # a cap at or below this marks an unmeasured account poor


def parse_caps(env):
    """AGENTKIT_CAPACITY_CAP=[<cli>]@profile=PCT[,...] -> [(cli|None, label, pct)].
    An invalid value is an error, never ignored: a drill must not run uncapped."""
    text = (env.get(CAP_VAR) or "").strip()
    caps = []
    if not text:
        return caps
    for entry in text.split(","):
        match = CAP_ENTRY.match(entry.strip().lower())
        if not match or int(match.group(3)) > 100:
            raise AkError("%s takes [<cli>]@profile=PERCENT[,...] with 0-100, e.g. @work=5 or codex@2=20"
                          % CAP_VAR)
        name = profiles.normalize(match.group(2)[1:])
        caps.append((match.group(1), usage._profile_label(name), int(match.group(3))))
    return caps


def cap_of(caps, cli, profile):
    """The lowest cap that applies to this account, or None."""
    found = [pct for c, p, pct in caps if p == profile and c in (None, cli)]
    return min(found) if found else None


def apply_cap(cand, caps):
    """Lower a candidate's headroom to the cap (lower-only). Returns the cap or None."""
    cap = cap_of(caps, cand["cli"], cand["profile"])
    if cap is None:
        return None
    cand["capped"] = True
    if cand["headroom_pct"] is not None:
        if cap < cand["headroom_pct"]:
            cand["headroom_pct"] = cap
            if cap <= 0 and cand["eligible"]:
                cand["eligible"] = False
                cand["excluded_reason"] = "no headroom (capped)"
    elif cap <= UNKNOWN_CAP_LIMIT:
        cand["_unknown_poor"] = True
    return cap


def choose(rows, model=None, reserve=DEFAULT_RESERVE, needs=(), count=1, exclude=(), allow_unknown=False, now=0,
           caps=(), leases=None, owner=None):
    """The decision over usage-v1 rows (already in providers.toml + profile
    order). Returns (chosen, candidates, soonest_reset). `leases` (active
    lease records) adds `leases` to each candidate; with `owner` it also
    excludes accounts leased exclusively to others and divides headroom by
    1 + leases held by others."""
    cands = []
    for index, row in enumerate(rows):
        if row["profile"] in exclude:
            continue
        cand = evaluate(row, model, reserve, needs, now)
        cand["_order"] = index
        apply_cap(cand, caps)
        if (allow_unknown and cand["_unknown"] and cand.get("_connected") and not needs
                and not cand.get("_unknown_poor")):
            cand["eligible"] = True
            cand["excluded_reason"] = None
        cand["_others"] = 0
        if leases is not None:
            held = [r for r in leases if r["cli"] == cand["cli"] and r["profile"] == cand["profile"]]
            others = [r for r in held if r["owner"] != owner] if owner else held
            cand["leases"] = len(others)
            if owner:
                cand["_others"] = len(others)
                blocking = [r for r in others if r.get("exclusive")]
                if blocking and cand["eligible"]:
                    cand["eligible"] = False
                    cand["excluded_reason"] = "leased to %s until %s" % (blocking[0]["owner"], blocking[0]["expires_at"])
        cands.append(cand)
    far = float("inf")

    def rank(c):
        measured = c["headroom_pct"] is not None
        return (0 if c["eligible"] else 1,
                0 if measured else 1,
                -((c["headroom_pct"] or 0) / (1.0 + c["_others"])),
                usage.epoch_of(c["_long_reset"]) if c["_long_reset"] else far,
                c["_order"])

    cands.sort(key=rank)
    chosen = [c for c in cands if c["eligible"]][:count]
    resets = [c["resets_at"] for c in cands if c["resets_at"] and c["headroom_pct"] is not None]
    soonest = min(resets, key=usage.epoch_of) if resets else None
    return [_public(c) for c in chosen], [_public(c) for c in cands], soonest


def _public(cand):
    return {k: v for k, v in cand.items() if not k.startswith("_")}


# ------------------------------------------------------------------- cli

def parse_args(args):
    opts = {"target": None, "profile": None, "model": None, "needs": [], "reserve": DEFAULT_RESERVE,
            "count": 1, "exclude": [], "allow_unknown": False, "json": False, "timeout": None,
            "owner": None, "max_age": state.DEFAULT_MAX_AGE}

    def value(i, flag):
        if i >= len(args):
            raise AkError("%s needs a value. See: ak pick --help" % flag)
        return args[i]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--allow-unknown":
            opts["allow_unknown"] = True
        elif arg == "--model":
            i += 1
            opts["model"] = value(i, arg)
            if not _norm(opts["model"]):
                raise AkError("--model needs a model name (fable, opus, ...)")
        elif arg == "--need":
            i += 1
            match = re.fullmatch(r"([a-z0-9][a-z0-9-]{0,40}):(\d{1,3})", value(i, arg))
            if not match or not 1 <= int(match.group(2)) <= 100:
                raise AkError("--need takes WINDOW:PERCENT, e.g. 5h:30 or 7d:20 (1-100)")
            opts["needs"].append((match.group(1), int(match.group(2))))
        elif arg == "--reserve":
            i += 1
            text = value(i, arg)
            if not text.isdigit() or int(text) > MAX_RESERVE:
                raise AkError("--reserve takes a percent from 0 to %d" % MAX_RESERVE)
            opts["reserve"] = int(text)
        elif arg == "--count":
            i += 1
            text = value(i, arg)
            if not text.isdigit() or not 1 <= int(text) <= MAX_COUNT:
                raise AkError("--count takes a number from 1 to %d" % MAX_COUNT)
            opts["count"] = int(text)
        elif arg == "--exclude":
            i += 1
            text = value(i, arg)
            if not text.startswith("@"):
                raise AkError("--exclude takes a profile, e.g. @work")
            opts["exclude"].append(usage._profile_label(profiles.normalize(text[1:])))
        elif arg == "--owner":
            i += 1
            opts["owner"] = lease.check_owner(value(i, arg))
        elif arg == "--max-age":
            i += 1
            opts["max_age"] = state_max_age(value(i, arg))
        elif arg == "--timeout":
            i += 1
            text = value(i, arg)
            if not text.isdigit() or not 1 <= int(text) <= usage.MAX_TIMEOUT:
                raise AkError("--timeout needs a number of seconds from 1 to %d" % usage.MAX_TIMEOUT)
            opts["timeout"] = int(text)
        elif arg.startswith("-"):
            raise AkError("unknown option '%s'. See: ak pick --help" % arg)
        elif arg.startswith("@"):
            if opts["profile"] is not None:
                raise AkError("only one @profile can be given")
            opts["profile"] = usage._profile_label(profiles.normalize(arg[1:]))
        else:
            if opts["target"] is not None:
                raise AkError("only one kind or CLI can be given")
            opts["target"] = arg
        i += 1
    if not opts.get("help") and opts["target"] is None:
        raise AkError("ak pick needs a kind or CLI, e.g. ak pick claude. See: ak pick --help")
    return opts


def state_max_age(text):
    if not text.isdigit() or int(text) > state.MAX_MAX_AGE:
        raise AkError("--max-age takes seconds from 0 to %d" % state.MAX_MAX_AGE)
    return int(text)


def render_json(opts, chosen, candidates, soonest, now):
    doc = {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": usage.iso_utc(now), "owner": opts["owner"],
           "target": opts["target"], "model": opts["model"], "reserve_pct": opts["reserve"],
           "need": [{"window": w, "min_free_pct": p} for w, p in opts["needs"]],
           "count": opts["count"], "chosen": chosen, "candidates": candidates, "soonest_reset": soonest}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def _line(c, now):
    room = "unknown" if c["headroom_pct"] is None else "%s%%" % c["headroom_pct"]
    text = "%s %s  headroom %s%s" % (c["cli"], c["profile"], room, "  (ak %s default)" % c["cli"] if c.get("default") else "")
    if c["binding_window"]:
        text += "  binding %s  resets %s" % (c["binding_window"], usage._relative(c["resets_at"], now))
    return text


def main(model, args, env, now=None, stdout=None):
    import sys
    stdout = stdout or sys.stdout
    opts = parse_args(args)
    if opts.get("help"):
        usage.emit(stdout, USAGE)
        return EXIT_OK
    now = usage.common_now() if now is None else now
    rows = usage.filter_rows(model, usage.enumerate_rows(model, env), opts["target"], opts["profile"])
    if not rows:
        common.warn("nothing to pick from: no profile or login matches. Try: ak usage")
        return EXIT_NOTHING
    caps = parse_caps(env)
    results = usage.mark_defaults(model, usage.fetch_cached(rows, env, opts["timeout"], now, opts["max_age"]), env)
    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    chosen, candidates, soonest = choose(results, opts["model"], opts["reserve"], opts["needs"], opts["count"],
                                         opts["exclude"], opts["allow_unknown"], now, caps,
                                         lease.active(env, now), opts["owner"])
    if opts["json"]:
        usage.emit(stdout, render_json(opts, chosen, candidates, soonest, now))
    else:
        usage.emit(stdout, "".join(_line(c, now) + "\n" for c in chosen))
    if not chosen:
        hint = (" Soonest reset: %s." % usage._relative(soonest, now)) if soonest else ""
        reasons = "; ".join("%s %s" % (c["profile"], c["excluded_reason"]) for c in candidates[:4])
        common.warn("no %s account has room (%s).%s" % (opts["target"], reasons, hint))
        return EXIT_NONE
    if len(chosen) < opts["count"]:
        common.warn("only %d of %d accounts qualify" % (len(chosen), opts["count"]))
    return EXIT_OK
