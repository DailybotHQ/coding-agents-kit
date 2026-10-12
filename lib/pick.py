"""`ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--reserve PCT]
[--count N] [--exclude @profile]... [--allow-unknown] [--owner ADDR [--reuse @profile]...] [--max-age S] [--json]
[--timeout SECONDS]`
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
- with --owner, an account leased exclusively (Codex) to anyone, the owner
  included, is excluded and the rest rank by headroom / (1 + its active
  leases): a lead that leases every lane under its own address must not get
  an account it already handed out. `--reuse @profile` exempts the owner's
  own lease on that account (handing it on, e.g. to a successor);
- every candidate carries `verdict` (ok, low, critical, unknown: ak
  capacity's rule), so an unknown-capacity account chosen with
  --allow-unknown says so.

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
               [--count N] [--exclude @profile]... [--allow-unknown] [--owner ADDR [--reuse @profile]...]
               [--max-age S] [--json] [--timeout SECONDS]
The account(s) with the most usable headroom for a kind, from the same rows as
ak usage (read-only: no login is refreshed, no reset is spent).
  --model NAME      model-scoped weekly windows of that model also govern (fable, opus, ...)
  --need WIN:PCT    the window with id WIN (5h, 7d, 7d-fable) must keep PCT% free
  --reserve PCT     keep PCT% of every window of 7 days or more unused (default 10, max 50)
  --count N         up to N distinct accounts, best first (default 1, max 16)
  --exclude @name   leave an account out (repeatable), e.g. one already busy
  --allow-unknown   connected accounts with no readable quota may be chosen, last
  --owner ADDR      choose for this lease owner: skip Codex accounts leased to anyone,
                    rank by headroom / (1 + active leases) (see ak lease)
  --reuse @name     with --owner: the owner's own lease on @name neither blocks nor
                    counts (handing that account on, e.g. to a successor); repeatable
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
DEFAULT_LOW = 25            # ak capacity's thresholds; the low one also marks a capped unmeasured account poor
DEFAULT_CRITICAL = 10


def _pct(text, what):
    if not isinstance(text, str) or not text.isdigit() or int(text) > 100:
        raise AkError("%s takes a percent from 0 to 100" % what)
    return int(text)


def thresholds(env, low=None, critical=None):
    """(low, critical): the flags, else AGENTKIT_CAPACITY_LOW / _CRITICAL, else 25 / 10."""
    low = low if low is not None else (_pct(env["AGENTKIT_CAPACITY_LOW"], "AGENTKIT_CAPACITY_LOW")
                                       if env.get("AGENTKIT_CAPACITY_LOW") else DEFAULT_LOW)
    critical = critical if critical is not None else (
        _pct(env["AGENTKIT_CAPACITY_CRITICAL"], "AGENTKIT_CAPACITY_CRITICAL")
        if env.get("AGENTKIT_CAPACITY_CRITICAL") else DEFAULT_CRITICAL)
    if critical > low:
        raise AkError("the critical threshold (%d) must not be above the low one (%d)" % (critical, low))
    return low, critical


def verdict(status, headroom, low=DEFAULT_LOW, critical=DEFAULT_CRITICAL, cap=None):
    """ak capacity's verdict for one reading: critical when rate limited or
    at/below critical, low at/below low, ok above, unknown with no headroom;
    an unmeasured account capped at/below low reads as the cap (lower-only)."""
    def of(room):
        if status == "rate_limited":
            return "critical"
        if room is None:
            return "unknown"
        if room <= critical:
            return "critical"
        return "low" if room <= low else "ok"
    result = of(headroom)
    if cap is not None and headroom is None and result == "unknown" and of(cap) in ("low", "critical"):
        result = of(cap)
    return result


def _cap_owner(model, name):
    """The usage-row owner a cap's CLI part names: a CLI or provider as is; a
    kind -> its provider's rows when the provider has a usage table, else its
    CLI's. Anything else is an error (a typo must never disable a drill)."""
    name = model.canonical(name)
    if name in model.providers or (name in model.clis and name not in model.kinds):
        return name
    if name in model.kinds:
        provider = model.kinds[name].get("provider")
        if provider and model.provider_usage(provider) is not None:
            return provider
        return model.kinds[name]["cli"]
    raise AkError("%s names '%s', which is no kind, CLI or provider" % (CAP_VAR, name))


def parse_caps(env, model=None):
    """AGENTKIT_CAPACITY_CAP=[<kind-or-cli>]@profile=PCT[,...] -> [(cli|None, label, pct)].
    An invalid value is an error, never ignored: a drill must not run uncapped."""
    text = (env.get(CAP_VAR) or "").strip()
    caps = []
    if not text:
        return caps
    for entry in text.split(","):
        match = CAP_ENTRY.match(entry.strip().lower())
        if not match or int(match.group(3)) > 100:
            raise AkError("%s takes [<kind-or-cli>]@profile=PERCENT[,...] with 0-100, e.g. @work=5 or codex@2=20"
                          % CAP_VAR)
        owner = match.group(1)
        if owner and model is not None:
            owner = _cap_owner(model, owner)
        name = profiles.normalize(match.group(2)[1:])
        caps.append((owner, usage._profile_label(name), int(match.group(3))))
    return caps


def cap_of(caps, cli, profile):
    """The lowest cap that applies to this account, or None."""
    found = [pct for c, p, pct in caps if p == profile and c in (None, cli)]
    return min(found) if found else None


def apply_cap(cand, caps, low=DEFAULT_LOW, needs=()):
    """Lower a candidate's headroom to the cap (lower-only): an account
    capped at 0, or below a --need percent, is no longer eligible; an
    unmeasured one capped at or below `low` is marked poor. `capped: true`
    says a cap applies (it may sit above the real reading). Returns the cap
    or None."""
    cap = cap_of(caps, cand["cli"], cand["profile"])
    if cap is None:
        return None
    cand["capped"] = True
    if cand["headroom_pct"] is not None:
        if cap < cand["headroom_pct"]:
            cand["headroom_pct"] = cap
        short = [pct for _wid, pct in needs if cap < pct]
        if cand["eligible"] and (cap <= 0 or short):
            cand["eligible"] = False
            cand["excluded_reason"] = ("capped at %d%%, needs %s%%" % (cap, _num(max(short)))) if short \
                else "no headroom (capped)"
    elif cap <= low:
        cand["_unknown_poor"] = True
    return cap


def choose(rows, model=None, reserve=DEFAULT_RESERVE, needs=(), count=1, exclude=(), allow_unknown=False, now=0,
           caps=(), leases=None, owner=None, low=DEFAULT_LOW, reuse=(), critical=DEFAULT_CRITICAL):
    """The decision over usage-v1 rows (already in providers.toml + profile
    order). Returns (chosen, candidates, soonest_reset). `leases` (active
    lease records) adds `leases` to each candidate; with `owner` it also
    excludes accounts leased exclusively to anyone (the owner included) and
    divides headroom by 1 + the active leases, except the owner's own lease on
    a profile in `reuse`."""
    cands = []
    for index, row in enumerate(rows):
        if row["profile"] in exclude:
            continue
        cand = evaluate(row, model, reserve, needs, now)
        cand["_order"] = index
        cap = apply_cap(cand, caps, low, needs)
        cand["verdict"] = verdict(row["status"], cand["headroom_pct"], low, critical, cap)
        if (allow_unknown and cand["_unknown"] and cand.get("_connected") and not needs
                and not cand.get("_unknown_poor")):
            cand["eligible"] = True
            cand["excluded_reason"] = None
        cand["_others"] = 0
        if leases is not None:
            held = [r for r in leases if r["cli"] == cand["cli"] and r["profile"] == cand["profile"]]
            if owner and cand["profile"] in reuse:
                held = [r for r in held if r["owner"] != owner]
            cand["leases"] = len(held)
            if owner:
                cand["_others"] = len(held)
                blocking = [r for r in held if r.get("exclusive")]
                if blocking and cand["eligible"]:
                    cand["eligible"] = False
                    mine = blocking[0]["owner"] == owner
                    cand["excluded_reason"] = "leased to %s%s until %s%s" % (
                        blocking[0]["owner"], " (this owner)" if mine else "", blocking[0]["expires_at"],
                        "; --reuse %s hands it on" % cand["profile"] if mine else "")
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


def one_per_profile(model, rows, target):
    """One row per profile, the account the launch uses (usage.account_row):
    `ak pick grok` must not offer grok @default and xai @default as two
    accounts when `ak grok @default` runs one of them. A still ambiguous
    profile keeps every row (each is named by its CLI or provider)."""
    groups = {}
    for r in rows:
        groups.setdefault(r.profile, []).append(r)
    keep = []
    for r in rows:
        group = groups[r.profile]
        try:
            one = usage.account_row(model, group, target, "pick")
        except AkError:
            one = None
        if one is None or one is r:
            keep.append(r)
    return keep


def _public(cand):
    return {k: v for k, v in cand.items() if not k.startswith("_")}


# ------------------------------------------------------------------- cli

def parse_args(args):
    opts = {"target": None, "profile": None, "model": None, "needs": [], "reserve": DEFAULT_RESERVE,
            "count": 1, "exclude": [], "allow_unknown": False, "json": False, "timeout": None,
            "owner": None, "reuse": [], "max_age": state.DEFAULT_MAX_AGE}

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
        elif arg == "--reuse":
            i += 1
            text = value(i, arg)
            if not text.startswith("@"):
                raise AkError("--reuse takes a profile, e.g. @work")
            opts["reuse"].append(usage._profile_label(profiles.normalize(text[1:])))
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
    if opts["reuse"] and not opts["owner"]:
        raise AkError("--reuse names the owner's own lease: it needs --owner. See: ak pick --help")
    return opts


def state_max_age(text):
    if not text.isdigit() or int(text) > state.MAX_MAX_AGE:
        raise AkError("--max-age takes seconds from 0 to %d" % state.MAX_MAX_AGE)
    return int(text)


def render_json(opts, chosen, candidates, soonest, now):
    doc = {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": usage.iso_utc(now), "owner": opts["owner"],
           "reuse": list(opts.get("reuse", [])),
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
    rows = one_per_profile(model, usage.filter_rows(model, usage.enumerate_rows(model, env), opts["target"],
                                                    opts["profile"]), opts["target"])
    if not rows:
        common.warn("nothing to pick from: no profile or login matches. Try: ak usage")
        return EXIT_NOTHING
    caps = parse_caps(env, model)
    try:
        low, critical = thresholds(env)
    except AkError:
        if caps:
            raise                     # a drill's cap needs valid thresholds
        low, critical = DEFAULT_LOW, DEFAULT_CRITICAL   # only the verdict uses them: never break ak pick
    results = usage.mark_defaults(model, usage.fetch_cached(rows, env, opts["timeout"], now, opts["max_age"]), env)
    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    chosen, candidates, soonest = choose(results, opts["model"], opts["reserve"], opts["needs"], opts["count"],
                                         opts["exclude"], opts["allow_unknown"], now, caps,
                                         lease.active(env, now), opts["owner"], low, opts["reuse"], critical)
    if opts["json"]:
        usage.emit(stdout, render_json(opts, chosen, candidates, soonest, now))
    else:
        usage.emit(stdout, "".join(_line(c, now) + "\n" for c in chosen))
    if not chosen:
        hint = (" Soonest reset: %s." % usage._relative(soonest, now)) if soonest else ""
        reasons = "; ".join("%s %s" % (c["profile"], c["excluded_reason"]) for c in candidates[:4])
        if not opts["allow_unknown"] and any((c["excluded_reason"] or "").startswith("no readable quota") for c in candidates):
            hint += " With no readable quota, ak pick %s --allow-unknown chooses a connected account (verdict unknown)." \
                % opts["target"]
        common.warn("no %s account has room (%s).%s" % (opts["target"], reasons, hint))
        return EXIT_NONE
    if len(chosen) < opts["count"]:
        common.warn("only %d of %d accounts qualify" % (len(chosen), opts["count"]))
    return EXIT_OK
