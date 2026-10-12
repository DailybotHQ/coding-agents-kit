"""`ak lease <kind> @profile --owner ADDR [--ttl DUR] [--purpose TEXT] [--json]`,
`ak lease release <kind> @profile --owner ADDR`, `ak lease ls [--json]`
— advisory, expiring account leases, so several leads never put two writers
on one Codex `auth.json` and `ak pick --owner` can spread lanes.

A lease names an account (the `ak usage` row identity: `glm @work` is the
Z.AI account `zai @work`), an owner address (a Herdr pane such as
local:w1:p2), an expiry and an optional purpose. A CLI marked
`lease = "exclusive"` in providers.toml (Codex) takes one lease at a time;
every other account takes many. Leases grant nothing: they are data that
`ak pick --owner` and the orchestration skill respect.

Store: <state>/leases/leases.json (lib/state.py; 0600, dir 0700). Every
mutation runs under a portable mutex (an `os.mkdir` lock directory; a lock
older than LOCK_STALE seconds is broken) and is written atomically, so
readers never lock. Expired leases are dropped on every write and ignored on
every read. Nothing secret is stored: owners, profile names, times and a
purpose text whose token-shaped words are refused.
"""

import binascii
import json
import os
import re
import shutil
import sys
import time

import common
import state
from common import AkError, EXIT_OK

SCHEMA = "leases-v1"
STORE_SCHEMA = "lease-store-v1"
EXIT_HELD = 1         # exclusive and held by another owner / nothing to release
EXIT_NOTHING = 3      # no such account
DEFAULT_TTL = 4 * 3600
MIN_TTL = 60
MAX_TTL = 24 * 3600
LOCK_WAIT = 5.0
LOCK_STALE = 30.0
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._@/-]{0,79}$")
DURATION = re.compile(r"^(\d{1,6})([smhd]?)$")
UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
PURPOSE_MAX = 80
# A word that looks like a credential: a known key prefix, or a long run of
# token characters mixing letters and digits.
KEY_PREFIX = re.compile(r"^(sk-|sk_|ghp_|gho_|github_pat_|xox[abp]-|AKIA|eyJ)")
LONG_TOKEN = re.compile(r"^[A-Za-z0-9_-]{24,}$")

USAGE = """usage: ak lease <kind-or-cli> @profile --owner ADDR [--ttl DUR] [--purpose TEXT] [--json]
       ak lease release <kind-or-cli> @profile --owner ADDR
       ak lease ls [--json]
Advisory, expiring leases on accounts, so two leads never put two writers on
one Codex account (Codex leases are exclusive; other accounts take many).
  --owner ADDR      who holds it, e.g. a Herdr pane address (local:w1:p2)
  --ttl DUR         expiry: N[s|m|h|d], from 60s to 24h (default 4h); the same
                    owner leasing again renews it
  --purpose TEXT    a short note (80 characters; never a secret)
Exit: 0 done · 1 held by another owner / no lease to release · 2 usage · 3 no such account
"""


# ---------------------------------------------------------------- checks

def check_owner(text):
    if not OWNER.match(text or ""):
        raise AkError("--owner takes an address of 1-80 letters, digits and ':._@/-', e.g. local:w1:p2")
    return text


def parse_ttl(text):
    match = DURATION.match(text or "")
    seconds = int(match.group(1)) * UNITS[match.group(2)] if match else 0
    if not MIN_TTL <= seconds <= MAX_TTL:
        raise AkError("--ttl takes N[s|m|h|d] from 60s to 24h, e.g. 90m or 4h")
    return seconds


def check_purpose(text):
    if text is None:
        return None
    if len(text) > PURPOSE_MAX or any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in text):
        raise AkError("--purpose takes up to %d printable characters" % PURPOSE_MAX)
    for word in re.split(r"[\s,;:=\"']+", text):
        if KEY_PREFIX.match(word) or (LONG_TOKEN.match(word) and re.search(r"\d", word) and re.search(r"[A-Za-z]", word)):
            raise AkError("--purpose looks like it holds a credential; leases store no secret")
    return text


# ----------------------------------------------------------------- store

def _dir(env):
    return os.path.join(state.root(env), "leases")


def _store(env):
    return os.path.join(_dir(env), "leases.json")


def _valid(rec):
    return (isinstance(rec, dict) and isinstance(rec.get("cli"), str) and isinstance(rec.get("profile"), str)
            and isinstance(rec.get("owner"), str) and isinstance(rec.get("expires_epoch"), (int, float))
            and not isinstance(rec.get("expires_epoch"), bool))


def _load(env):
    doc = state.read_json(_store(env))
    if not doc or doc.get("schema") != STORE_SCHEMA or not isinstance(doc.get("leases"), list):
        return []
    return [r for r in doc["leases"] if _valid(r)]


def active(env, now):
    """Every unexpired lease (public form), oldest first."""
    return [_public(r) for r in _load(env) if r["expires_epoch"] > now]


def _public(rec):
    import usage
    out = {"cli": rec["cli"], "profile": rec["profile"], "owner": rec["owner"],
           "exclusive": bool(rec.get("exclusive")), "purpose": rec.get("purpose"),
           "kind": rec.get("kind"), "created_at": usage.iso_utc(rec.get("created_epoch") or 0),
           "expires_at": usage.iso_utc(rec["expires_epoch"])}
    return out


class _Lock(object):
    """A mutex every OS provides atomically: mkdir of one directory, with a
    random token inside so a holder only ever removes its own lock. A lock
    older than LOCK_STALE (its holder died) is broken by an atomic rename,
    and only when the renamed lock still carries the token that was judged
    stale; anything else is put back."""

    def __init__(self, env):
        self.path = os.path.join(state.ensure_dir(_dir(env)), ".lock")
        self.token = binascii.hexlify(os.urandom(8)).decode()

    @staticmethod
    def _token_of(path):
        try:
            with open(os.path.join(path, "token")) as handle:
                return handle.read().strip()
        except OSError:
            return None

    def held(self):
        """Is the lock still ours? A stale-lock breaker racing a fresh holder
        can move a live lock aside; the holder then must not write."""
        return self._token_of(self.path) == self.token

    def _sweep_aside(self):
        directory = os.path.dirname(self.path)
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if name.startswith(".lock.stale-") and time.time() - os.stat(path).st_mtime > LOCK_STALE:
                shutil.rmtree(path, ignore_errors=True)

    def _break_stale(self):
        seen = self._token_of(self.path)
        if time.time() - os.stat(self.path).st_mtime <= LOCK_STALE:
            return
        if self._token_of(self.path) != seen:        # re-check right before the rename: narrows the race
            return
        aside = "%s.stale-%s" % (self.path, self.token)
        os.rename(self.path, aside)                  # atomic: one breaker wins
        if self._token_of(aside) != seen:            # a fresh lock replaced the stale one meanwhile
            try:
                os.rename(aside, self.path)
            except OSError:
                pass
            return
        shutil.rmtree(aside, ignore_errors=True)
        self._sweep_aside()

    def __enter__(self):
        deadline = time.time() + LOCK_WAIT
        while True:
            try:
                os.mkdir(self.path, 0o700)
                try:
                    with open(os.path.join(self.path, "token"), "w") as handle:
                        handle.write(self.token)
                except OSError:
                    shutil.rmtree(self.path, ignore_errors=True)
                    raise
                return self
            except FileExistsError:
                try:
                    self._break_stale()
                except OSError:
                    pass                         # gone already, or not removable: the deadline decides
                if time.time() > deadline:
                    raise AkError("the lease store is busy (%s); try again" % self.path, common.EXIT_INTERNAL)
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self._token_of(self.path) == self.token:      # never remove a lock another process holds
            try:
                os.unlink(os.path.join(self.path, "token"))
                os.rmdir(self.path)
            except OSError:
                pass
        return False


def _save_held(lock, env, records, now):
    if not lock.held():
        raise AkError("the lease store lock was taken over while this command held it; try again",
                      common.EXIT_INTERNAL)
    _save(env, records, now)


def _save(env, records, now):
    state.write_json(_store(env), {"schema": STORE_SCHEMA,
                                   "leases": [r for r in records if r["expires_epoch"] > now]})


def take(env, account, owner, ttl, purpose, now, kind=None):
    """Create or renew `owner`'s lease on account (cli, profile, exclusive).
    Returns (record, renewed). Raises AkError(EXIT_HELD) when an exclusive
    account is held by someone else."""
    cli, profile, exclusive = account
    with _Lock(env) as lock:
        records = [r for r in _load(env) if r["expires_epoch"] > now]
        mine = [r for r in records if r["cli"] == cli and r["profile"] == profile and r["owner"] == owner]
        others = [r for r in records if r["cli"] == cli and r["profile"] == profile and r["owner"] != owner]
        if exclusive and others:
            holder = _public(others[0])
            raise AkError("%s %s is leased to %s until %s (one writer at a time)"
                          % (cli, profile, holder["owner"], holder["expires_at"]), EXIT_HELD)
        if mine:
            rec = mine[0]
            rec.update({"expires_epoch": int(now + ttl), "exclusive": exclusive})
            if purpose is not None:
                rec["purpose"] = purpose
            renewed = True
        else:
            rec = {"cli": cli, "profile": profile, "owner": owner, "exclusive": exclusive, "kind": kind,
                   "purpose": purpose, "created_epoch": int(now), "expires_epoch": int(now + ttl)}
            records.append(rec)
            renewed = False
        _save_held(lock, env, records, now)
    return _public(rec), renewed


def release(env, account, owner, now):
    """Drop `owner`'s lease on the account. False when it held none."""
    cli, profile = account[0], account[1]
    with _Lock(env) as lock:
        records = [r for r in _load(env) if r["expires_epoch"] > now]
        keep = [r for r in records if not (r["cli"] == cli and r["profile"] == profile and r["owner"] == owner)]
        if len(keep) == len(records):
            return False
        _save_held(lock, env, keep, now)
    return True


# ------------------------------------------------------------------- cli

def resolve_account(model, env, target, profile):
    """(cli, profile, exclusive) of the one usage row a kind + @profile names."""
    import usage
    rows = usage.filter_rows(model, usage.enumerate_rows(model, env), target, profile)
    if not rows:
        raise AkError("no %s account %s: nothing to lease. Try: ak usage %s" % (target, profile, target), EXIT_NOTHING)
    row = rows[0]
    exclusive = model.clis.get(row.cli, {}).get("lease") == "exclusive"
    return row.cli, row.profile, exclusive


def parse_args(args):
    import profiles
    import usage
    opts = {"action": "take", "target": None, "profile": None, "owner": None, "ttl": DEFAULT_TTL,
            "purpose": None, "json": False}
    rest = list(args)
    if rest and rest[0] in ("release", "ls"):
        opts["action"] = rest.pop(0)

    def value(i, flag):
        if i >= len(rest):
            raise AkError("%s needs a value. See: ak lease --help" % flag)
        return rest[i]

    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--owner":
            i += 1
            opts["owner"] = check_owner(value(i, arg))
        elif arg == "--ttl" and opts["action"] == "take":
            i += 1
            opts["ttl"] = parse_ttl(value(i, arg))
        elif arg == "--purpose" and opts["action"] == "take":
            i += 1
            opts["purpose"] = check_purpose(value(i, arg))
        elif arg.startswith("-"):
            raise AkError("unknown option '%s'. See: ak lease --help" % arg)
        elif opts["action"] == "ls":
            raise AkError("ak lease ls takes no account. See: ak lease --help")
        elif arg.startswith("@"):
            if opts["profile"] is not None:
                raise AkError("only one @profile can be given")
            opts["profile"] = usage._profile_label(profiles.normalize(arg[1:]))
        else:
            if opts["target"] is not None:
                raise AkError("only one kind or CLI can be given")
            opts["target"] = arg
        i += 1
    if opts.get("help") or opts["action"] == "ls":
        return opts
    if opts["target"] is None or opts["profile"] is None:
        raise AkError("ak lease needs a kind and a @profile, e.g. ak lease codex @work --owner local:w1:p2")
    if opts["owner"] is None:
        raise AkError("ak lease needs --owner ADDR (the lease holder, e.g. your Herdr pane address)")
    return opts


def render_ls(records, now):
    import usage
    doc = {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": usage.iso_utc(now), "leases": records}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(model, args, env, now=None, stdout=None):
    import usage
    stdout = stdout or sys.stdout
    opts = parse_args(args)
    if opts.get("help"):
        usage.emit(stdout, USAGE)
        return EXIT_OK
    now = usage.common_now() if now is None else now
    if opts["action"] == "ls":
        records = active(env, now)
        if opts["json"]:
            usage.emit(stdout, render_ls(records, now))
        elif not records:
            usage.emit(stdout, "no active lease\n")
        else:
            usage.emit(stdout, "".join("%s %s  %s  until %s%s%s\n" % (
                r["cli"], r["profile"], r["owner"], r["expires_at"], "  exclusive" if r["exclusive"] else "",
                ("  " + r["purpose"]) if r["purpose"] else "") for r in records))
        return EXIT_OK
    account = resolve_account(model, env, opts["target"], opts["profile"])
    if opts["action"] == "release":
        if not release(env, account, opts["owner"], now):
            common.warn("%s holds no lease on %s %s" % (opts["owner"], account[0], account[1]))
            return EXIT_HELD
        usage.emit(stdout, "released %s %s (%s)\n" % (account[0], account[1], opts["owner"]))
        return EXIT_OK
    record, renewed = take(env, account, opts["owner"], opts["ttl"], opts["purpose"], now,
                           kind=model.canonical(opts["target"]))
    if opts["json"]:
        usage.emit(stdout, json.dumps(dict(record, renewed=renewed), indent=2, sort_keys=True) + "\n")
    else:
        usage.emit(stdout, "%s %s %s to %s until %s%s\n" % (
            "renewed" if renewed else "leased", record["cli"], record["profile"], record["owner"],
            record["expires_at"], "  (exclusive)" if record["exclusive"] else ""))
    return EXIT_OK
