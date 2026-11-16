"""The kit's own machine state: the usage cache (`ak capacity`, `ak pick`),
the lease store (`ak lease`) and the launch record (`ak last`, lib/last.py).

One directory per machine, shared by every process however it was launched:
`AGENTKIT_STATE_DIR`, else `$XDG_STATE_HOME/agentkit`, else
`<home>/.local/state/agentkit`, where <home> is the real home when a launch
relocated HOME (`AGENTKIT_REAL_HOME`). An `xdg`-isolated launch moves
XDG_STATE_HOME into its profile, so `profiles.activate` records the real
directory in AGENTKIT_STATE_DIR first.

Only numbers, labels, profile names, owner addresses and the working
directories of interactive launches are stored — never a credential, a key
name's value or a path under a profile. Directories are
0700, files 0600 and every write is atomic (temp file + os.replace), so a
reader never sees half a file. Portable: os.path and os.replace only.
"""

import json
import os
import tempfile

import common

CACHE_SCHEMA = "usage-cache-v1"
DEFAULT_MAX_AGE = 300
MAX_MAX_AGE = 86400
CACHE_NOTE = "the usage cache holds usage numbers only; ak usage is the only command that always reads live"

# The usage-v1 row keys the cache keeps (window keys below). Anything else
# a row may carry (the table's notes, future keys) is dropped.
ROW_KEYS = ("cli", "profile", "kinds", "plan", "status", "windows", "source", "reason", "error",
            "connected", "resets_available")
WINDOW_KEYS = ("id", "label", "used_pct", "resets_at", "window_seconds", "used", "limit", "unit")
# Only vendor readings are cached. A login problem (no_login, expired,
# no_scope), a row without a quota source and an error are cheap to re-detect
# or transient, and must show a fixed login at once.
CACHED = ("ok", "rate_limited")


def _profiles_root(env, home):
    data = env.get("AGENTKIT_HOME") or os.path.join(home, ".local", "share", "agentkit")
    return env.get("AGENTKIT_PROFILES_DIR") or os.path.join(data, "profiles")


def _inside(path, parent):
    path, parent = os.path.realpath(path), os.path.realpath(parent)
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def root(env=None):
    env = os.environ if env is None else env
    if env.get("AGENTKIT_STATE_DIR"):
        return env["AGENTKIT_STATE_DIR"]
    home = env.get("AGENTKIT_REAL_HOME") or env.get("HOME") or env.get("USERPROFILE") or common.home()
    xdg = env.get("XDG_STATE_HOME")
    # An XDG_STATE_HOME inside the profiles tree is a profile's own (an
    # `ak env` of an xdg-isolated kind printed it into a shell or pane): the
    # kit's state stays machine-wide, never under a profile.
    if xdg and not _inside(xdg, _profiles_root(env, home)):
        return os.path.join(xdg, "agentkit")
    return os.path.join(home, ".local", "state", "agentkit")


def ensure_dir(path):
    """Create `path` (and a missing state root above it) private to the user."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        ensure_dir(parent)
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o700, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def write_json(path, doc):
    """Atomically replace `path` with `doc` as JSON, mode 0600."""
    directory = ensure_dir(os.path.dirname(path))
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(doc, handle, indent=1, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    """The JSON object at `path`, or None when it is missing or unreadable."""
    try:
        with open(path) as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- cache

def _cache_path(env, cli, profile):
    return os.path.join(root(env), "usage-cache", "%s%s.json" % (cli, profile))


def _clean_row(row):
    out = {k: row[k] for k in ROW_KEYS if k in row}
    out["windows"] = [{k: w[k] for k in WINDOW_KEYS if k in w} for w in row.get("windows") or []
                      if isinstance(w, dict)]
    return out


def cache_put(env, row, now):
    """Remember one usage-v1 row (best effort: a write failure is ignored)."""
    if row.get("status") not in CACHED or not row.get("cli") or not row.get("profile"):
        return False
    try:
        write_json(_cache_path(env, row["cli"], row["profile"]),
                   {"schema": CACHE_SCHEMA, "cached_at": int(now), "row": _clean_row(row)})
    except OSError:
        return False
    return True


def cache_get(env, cli, profile, now, max_age):
    """(row, age_seconds) when a fresh entry exists for this account, else
    (None, None). A corrupt, foreign or future-dated entry is a miss."""
    if max_age <= 0:
        return None, None
    doc = read_json(_cache_path(env, cli, profile))
    if not doc or doc.get("schema") != CACHE_SCHEMA:
        return None, None
    row, stamp = doc.get("row"), doc.get("cached_at")
    if not isinstance(row, dict) or not isinstance(stamp, int) or isinstance(stamp, bool):
        return None, None
    if row.get("cli") != cli or row.get("profile") != profile or not isinstance(row.get("windows"), list):
        return None, None
    age = int(now) - stamp
    if age < 0 or age > max_age:
        return None, None
    return _clean_row(row), age


# ------------------------------------------------------- advisory tokens
# One immutable sample file per observed run, written once and never
# rewritten: concurrent runs cannot lose each other's observations (no
# read-modify-write exists), a crashed write leaves one partial file the
# reader skips, and the sums are recomputed from the samples at read time.
# .agentkit-orig-style durability is not needed: samples are additive
# evidence, each carrying only what its own run reported.

_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write", "total")
_TOKEN_SAMPLES_MAX = 5000


def _tokens_dir(env, cli, profile):
    return os.path.join(root(env), "token-samples", "%s%s" % (cli, profile))


def tokens_add(env, cli, profile, tokens, now):
    """Record one observed run's REPORTED token counts as an immutable
    sample file. Only non-null fields count: a run that reported nothing
    is not recorded, and no field is ever imputed. Best effort: a write
    failure loses that one sample and is otherwise silent."""
    counted = {k: tokens[k] for k in _TOKEN_KEYS
               if isinstance(tokens.get(k), int) and not isinstance(tokens.get(k), bool)}
    if not counted or not cli or not profile:
        return False
    directory = _tokens_dir(env, cli, profile)
    try:
        os.makedirs(directory, exist_ok=True)
        fd, staged = tempfile.mkstemp(dir=directory, prefix="sample-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"cli": cli, "profile": profile,
                       "tokens": {k: counted.get(k) for k in _TOKEN_KEYS},
                       "recorded_at": int(now)}, fh)
        os.replace(staged, os.path.join(directory, "sample-%d-%d.json" % (int(now), os.getpid())))
    except OSError:
        return False
    return True


def tokens_get(env, cli, profile):
    """The advisory sums for one account over its recorded samples:
    {"runs": n, "tokens": {..}} or {} when nothing was ever observed —
    absence is not zero, it is unknown. Each sample contributes only the
    fields its own run reported; totals are never synthesized."""
    directory = _tokens_dir(env, cli, profile)
    if not os.path.isdir(directory):
        return {}
    runs = 0
    sums = {k: 0 for k in _TOKEN_KEYS}
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return {}
    for name in names[-_TOKEN_SAMPLES_MAX:]:
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
                sample = json.load(fh)
        except (OSError, ValueError):
            continue  # a partial or corrupt sample is skipped, not counted
        if not isinstance(sample, dict) or sample.get("cli") != cli:
            continue
        reported = sample.get("tokens")
        if not isinstance(reported, dict) or not any(
                isinstance(v, int) and not isinstance(v, bool) for v in reported.values()):
            continue
        runs += 1
        for k in _TOKEN_KEYS:
            v = reported.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                sums[k] += v
    if not runs:
        return {}
    return {"runs": runs, "tokens": sums}


def tokens_prune(env, cli, profile):
    """Drop samples beyond the reader's window (housekeeping, optional):
    oldest first."""
    directory = _tokens_dir(env, cli, profile)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    for name in names[:-_TOKEN_SAMPLES_MAX]:
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            pass
