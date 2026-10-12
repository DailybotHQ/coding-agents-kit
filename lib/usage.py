"""`ak usage [<kind-or-cli>] [@profile] [--json] [--timeout SECONDS] [--no-color]`
— the quota and usage of every account the kit can see, one row per
credential identity.

The sources are data (`[clis.<cli>.usage]` / `[providers.<id>.usage]` in
providers.toml); only the parsing of a response is code (an Adapter). The
endpoints are vendor-internal and unofficial: a changed shape is reported as
an `error` row, never a crash.

Secret discipline: a token lives in memory and in one request header. It is
never in a message, a log, the table, `--json` or a file. Nothing is
refreshed and nothing is written under a profile or the env file. The only
file written is the kit's own usage cache (lib/state.py: usage numbers,
0600), which every live read refreshes for `ak capacity` and `ak pick`.

Portable on purpose (Linux, macOS, Windows): os.path, urllib, threads and
subprocess only; the few OS decisions sit in `Platform`.
"""

import datetime
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

import common
import kinds
import profiles
import state
from common import AkError, EXIT_OK, EXIT_USAGE

SCHEMA = "usage-v1"
EXIT_PROBLEM = 1      # at least one row is not ok / unsupported
EXIT_NOTHING = 3      # nothing to report for the requested filter

STATUSES = ("ok", "expired", "no_login", "no_scope", "rate_limited", "unsupported", "error")
PROBLEM_STATUSES = ("expired", "no_login", "no_scope", "rate_limited", "error")
ROW_EXTRAS = ("resets_available",)   # optional usage-v1 row keys an adapter may add

DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 60
MAX_BODY = 1 << 20    # 1 MiB
MAX_WORKERS = 8
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")

USAGE = """usage: ak usage [<kind-or-cli>] [@profile] [-v | --verbose] [--json] [--timeout SECONDS] [--no-color]
Quota and usage of each account the kit can see (read-only; no token is printed,
refreshed or written). The sources are vendor-internal and unofficial.
The table fits the terminal: accounts without a readable quota are folded into
one n/d line and long notes are shortened; -v lists every row with its full note.
"""


# ------------------------------------------------------------- platform

class Platform(object):
    """The few OS decisions of the command, injectable so tests can simulate
    Linux, macOS and Windows on any host."""

    def __init__(self, name=None, is_tty=False, encoding="utf-8", env=None, columns=None):
        self.name = name or common.os_name()
        self.is_tty = is_tty
        self.encoding = (encoding or "ascii").lower()
        self.env = env if env is not None else {}
        self.columns = columns            # terminal width, or None (no fitting: pipes, files)

    @classmethod
    def current(cls, env, stream=None):
        stream = stream or sys.stdout
        try:
            tty = bool(stream.isatty())
        except (AttributeError, ValueError):
            tty = False
        columns = None
        if tty:
            try:
                columns = int(env.get("COLUMNS") or 0) or os.get_terminal_size(stream.fileno()).columns
            except (AttributeError, ValueError, OSError):
                columns = None
        return cls(common.os_name(), tty, getattr(stream, "encoding", None) or "ascii", env, columns)

    def utf8_stdout(self):
        return "utf" in self.encoding

    def supports_color(self, no_color_flag=False):
        if no_color_flag or not self.is_tty or self.env.get("NO_COLOR") or self.env.get("TERM") == "dumb":
            return False
        if self.name == "windows":
            return bool(self.env.get("WT_SESSION") or self.env.get("ANSICON") or self.env.get("TERM_PROGRAM")
                        or self.env.get("TERM"))
        return True


# ---------------------------------------------------- credentials/adapters

class Credential(object):
    """A bearer token and what is known about it. Never printed."""

    def __init__(self, token, expires_at=None, scopes=None, plan=None):
        self.token = token
        self.expires_at = expires_at      # epoch seconds, or None when unknown
        self.scopes = scopes              # list of scope names, or None when unknown
        self.plan = plan

    def __repr__(self):
        return "<Credential>"


class Failure(object):
    """A row-level outcome that stops the pipeline: a status and a one-line
    message that never contains a secret."""

    def __init__(self, status, message, short=None):
        assert status in STATUSES and status != "ok"
        self.status = status
        self.message = message
        self.short = short


class ShapeError(Exception):
    """The response did not have the documented shape."""


class NoQuota(Exception):
    """The response is well formed but reports no limit to show; the message
    is the one-line reason of the resulting `unsupported` row."""


class Adapter(object):
    """Parser of one source. Subclasses set `id` and implement the two hooks;
    transport, timeouts and secrecy belong to the pipeline."""

    id = None
    required_scope = None     # a scope the endpoint needs, when the login file lists scopes

    def credential_from_file(self, doc):
        """doc: the parsed login file. -> Credential or Failure."""
        raise NotImplementedError

    def parse(self, doc):
        """doc: the parsed response. -> (plan or None, [window dict])."""
        raise ShapeError("no parser")

    def extras(self, doc):
        """Optional row keys of usage-v1 read from the same response (e.g.
        resets_available). Never raises: an extra that is missing or odd is
        simply absent."""
        return {}


ADAPTERS = {}


def register(adapter):
    ADAPTERS[adapter.id] = adapter
    return adapter


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean_text(value, limit=60):
    """Text that came from a vendor response is shown on a terminal: drop
    control characters (no escape sequence can reach the screen) and cap it."""
    return _CONTROL.sub("", str(value))[:limit]


def window(wid, label, used_pct, resets_at, window_seconds, amount=None):
    """One window of a row (usage-v1). used_pct is clamped to 0..100.
    amount: optional (used, limit, unit) when the source reports absolute
    numbers (Z.AI credits); it adds the optional keys used, limit and unit."""
    wid, label = clean_text(wid), clean_text(label)
    if used_pct is not None:
        if not math.isfinite(float(used_pct)):
            raise ShapeError("not a finite number")
        used_pct = max(0.0, min(100.0, float(used_pct)))
        used_pct = int(used_pct) if used_pct == int(used_pct) else round(used_pct, 1)
    out = {"id": wid, "label": label, "used_pct": used_pct, "resets_at": resets_at,
           "window_seconds": window_seconds}
    if amount is not None:
        used, limit, unit = amount
        out.update({"used": used, "limit": limit, "unit": clean_text(unit, 16)})
    return out


def iso_utc(epoch_seconds):
    return datetime.datetime.fromtimestamp(int(epoch_seconds), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value):
    """An ISO-8601 string, or epoch seconds/milliseconds, -> ISO UTC string
    (or None when it is not a time or is out of range)."""
    try:
        return _parse_time(value)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_time(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return iso_utc(seconds)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{9,13}(\.\d+)?", text):
            return _parse_time(float(text))
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?", text)
        if not match:
            return None
        y, mo, d, h, mi, s = [int(x) for x in match.groups()[:6]]
        stamp = datetime.datetime(y, mo, d, h, mi, s)
        tz = match.group(8)
        if tz and tz != "Z":
            sign = 1 if tz[0] == "+" else -1
            digits = tz[1:].replace(":", "")
            stamp -= sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def epoch_of(iso):
    stamp = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return (stamp - datetime.datetime(1970, 1, 1)).total_seconds()


# ----------------------------------------------------------------- rows

class Row(object):
    """One credential identity to report."""

    def __init__(self, cli, profile, kind_names, spec, source, ctx=None, key_var=None, unsupported=None, short=None):
        self.cli = cli                    # CLI or provider id owning the credential
        self.profile = profile            # '@default' or '@name'
        self.kind_names = kind_names
        self.spec = spec                  # usage table (dict) or None
        self.source = source              # adapter id or 'none'
        self.ctx = ctx                    # kinds.Context for file credentials
        self.key_var = key_var            # env var holding the key (provider rows)
        self.unsupported = unsupported    # reason, for n/d rows
        self.short = short                # the table's few-word form of that reason
        self.connected = None             # n/d rows: True / False / None (cannot tell)
        self.how = None                   # ... and how: "logged in" or "<KEY> set"


def _cli_order(model):
    return list(model.clis)


def _kinds_of_cli(model, cli_name):
    return sorted(n for n, k in model.kinds.items() if k["cli"] == cli_name)


def _kinds_of_provider(model, provider):
    return sorted(n for n, k in model.kinds.items() if k.get("provider") == provider)


def _profile_label(name):
    return profiles.label(name)


def _context(model, env, cli_name, name):
    kind = model.kind(cli_name)
    home = env.get("HOME") or env.get("USERPROFILE") or common.home()
    if name:
        return kinds.Context(kind, env, home, profile_dir=profiles.path(cli_name, name), profile_label=_profile_label(name))
    return kinds.Context(kind, env, home)


def _installed(model, env, cli_name):
    try:
        return bool(common.resolve_executable(model.clis[cli_name], env))
    except Exception:
        return False


def enumerate_rows(model, env):
    """Every row the kit can see, in the documented order, before filtering."""
    listing = {}
    profile_dirs = {}
    for cli_name, name, directory in profiles.listing(model, env):
        listing.setdefault(cli_name, []).append(name)
        profile_dirs.setdefault(cli_name, set()).add(os.path.realpath(directory))
    rows = []
    covered = set()      # (cli, profile label) already reported through a provider key
    # provider-key rows (one per key variable that is set)
    provider_rows = []
    for pname, prov in model.providers.items():
        table = model.provider_usage(pname)
        if table is None:
            continue
        base = prov["key"]
        names = sorted(n for n in env if env.get(n) and (n == base or n.startswith(base + "_")))
        for var in names:
            suffix = var[len(base) + 1:] if var != base else ""
            label = "@default"
            if suffix:
                label = _profile_label(_match_profile_name(listing, suffix))
            kind_names = _kinds_of_provider(model, pname)
            if "unsupported" in table:
                row = Row(pname, label, kind_names, table, "none", unsupported=table["unsupported"], short=table.get("short"))
                row.connected, row.how = True, "%s set" % var
            else:
                row = Row(pname, label, kind_names, table, table["adapter"], key_var=var)
            provider_rows.append(row)
            for kn in kind_names:
                covered.add((model.kinds[kn]["cli"], label))
    # subscription / harness rows
    for cli_name in _cli_order(model):
        table = model.cli_usage(cli_name)
        installed = _installed(model, env, cli_name)
        # A default home moved onto a profile directory (CLAUDE_CONFIG_DIR=<profile>)
        # is that profile's account: one row, so ak pick never counts it twice.
        home_env = model.clis[cli_name].get("home_env")
        moved = env.get(home_env) if home_env else None
        same_as_profile = bool(moved) and os.path.realpath(moved) in profile_dirs.get(cli_name, set())
        candidates = [None] if installed and not same_as_profile else []
        candidates.extend(sorted(listing.get(cli_name, [])))
        for name in candidates:
            label = _profile_label(name) if name else "@default"
            kind_names = [cli_name] if table is None else _kinds_of_cli(model, cli_name)
            if table is None:
                if (cli_name, label) in covered:
                    continue
                example = next((k for k in _kinds_of_cli(model, cli_name) if k != cli_name), None)
                hint = "; its usage shows up under the provider key of a kind such as %s" % example if example else ""
                rows.append(_with_login(model, env, cli_name, name, Row(
                    cli_name, label, [cli_name], None, "none",
                    unsupported="%s has no usage source of its own%s" % (cli_name, hint), short="via a provider key")))
            elif "unsupported" in table:
                rows.append(_with_login(model, env, cli_name, name, Row(
                    cli_name, label, kind_names, table, "none", unsupported=table["unsupported"], short=table.get("short"))))
            else:
                rows.append(Row(cli_name, label, [cli_name], table, table["adapter"],
                                ctx=_context(model, env, cli_name, name)))
    return _order(rows + provider_rows, model)


def _with_login(model, env, cli_name, name, row):
    """An n/d row still says whether its account is connected: the CLI's
    login probe (file presence, credential variable names, Keychain item
    presence; no credential is read)."""
    try:
        row.connected = profiles.login_state(model, cli_name, name, env)
    except Exception:
        row.connected = None
    row.how = "logged in" if row.connected else None
    return row


def _match_profile_name(listing, suffix):
    for names in listing.values():
        for name in names:
            if profiles.suffix(name) == suffix:
                return name
    return suffix.lower()


def _order(rows, model):
    order = {n: i for i, n in enumerate(_cli_order(model) + sorted(model.providers))}

    def key(row):
        return (order.get(row.cli, len(order)), 0 if row.profile == "@default" else 1, row.profile)
    return sorted(rows, key=key)


def filter_rows(model, rows, target, profile):
    if target is not None:
        target = model.canonical(target)
        if target not in model.kinds and target not in model.clis and target not in model.providers:
            raise AkError("unknown kind, CLI or provider '%s'. Kinds: %s" % (target, " ".join(model.kind_names())))
        rows = [r for r in rows if r.cli == target or target in r.kind_names]
    if profile is not None:
        rows = [r for r in rows if r.profile == profile]
    return rows


# ------------------------------------------------------------ transport

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HttpFailure(Exception):
    """Transport failure with a message that cannot hold a secret."""


def resolve_url(row, env):
    table_url = row.spec["url"]
    override = env.get("AGENTKIT_USAGE_URL_" + row.source.upper().replace("-", "_"))
    if override:
        parts = urllib.parse.urlsplit(override)
        host = (parts.hostname or "")
        if parts.scheme not in ("http", "https") or host not in [h.strip("[]") for h in LOOPBACK_HOSTS]:
            raise AkError("AGENTKIT_USAGE_URL_%s must point to a loopback host (127.0.0.1, localhost, ::1)"
                          % row.source.upper().replace("-", "_"))
        return override
    if not table_url.startswith("https://"):
        raise AkError("usage source %s has a non-https URL" % row.source, common.EXIT_INTERNAL)
    return table_url


def _timed_out(exc):
    if isinstance(exc, socket.timeout):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(getattr(exc, "reason", None), socket.timeout)


def _is_loopback(url):
    return (urllib.parse.urlsplit(url).hostname or "") in [h.strip("[]") for h in LOOPBACK_HOSTS]


def http_get(url, headers, timeout):
    """One GET: no redirect followed, body capped. -> (status, bytes).
    A failure carries a message built from the exception class only. A
    loopback URL (the test override) never goes through a proxy."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    handlers = [_NoRedirect()]
    if _is_loopback(url):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(MAX_BODY + 1)
        except Exception:
            return exc.code, b""
    except Exception as exc:
        if _timed_out(exc):
            raise HttpFailure("timed out after %ds" % timeout)
        raise HttpFailure("network error (%s)" % exc.__class__.__name__)


# ------------------------------------------------------------ evaluation

def _result(row, status, plan=None, windows=None, error=None, reason=None, short=None):
    """A row's result. `_short` is the table's few-word note; keys starting
    with '_' never reach --json (render_json drops them)."""
    plan = clean_text(plan) if plan is not None else None
    return {"cli": row.cli, "profile": row.profile, "kinds": list(row.kind_names), "plan": plan or None, "status": status,
            "windows": windows or [], "source": row.source, "error": error, "reason": reason, "_short": short}


def _read_login_file(row):
    """First existing login file of the row's context -> parsed JSON, None
    (no file), or Failure."""
    for ref in row.spec.get("files", []):
        path = row.ctx.ref_path(ref)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                return Failure("error", "the login file is unexpectedly large")
            return json.loads(raw.decode("utf-8-sig"))
        except (OSError, ValueError):
            return Failure("error", "the login file could not be read as JSON")
    return None


def credential_of(row, env, adapter):
    """-> Credential or Failure for a row, without any network."""
    if row.spec.get("credential") == "env":
        token = env.get(row.key_var or "", "")
        return Credential(token) if token else Failure("no_login", "%s is not set" % row.key_var)
    doc = _read_login_file(row)
    if isinstance(doc, Failure):
        return doc
    if doc is None:
        doc = read_keychain(row, env)
        if isinstance(doc, Failure):
            return doc
    if doc is None:
        return Failure("no_login", "no login found for this profile", short="log in: %s" % _launch_hint(row))
    return adapter.credential_from_file(doc)


def _launch_hint(row):
    """The command that opens this row's account, for a short table note."""
    return "ak %s" % row.cli if row.profile == "@default" else "ak %s %s" % (row.cli, row.profile)


def os_name():
    """Indirection so tests can simulate another OS."""
    return common.os_name()


def keychain_service(row):
    """The macOS Keychain service holding the row's login, or None. The
    default home uses the spec's service as is; with `keychain_profile`, a
    profile directory uses `<service>-<first 8 hex of sha256(directory)>`,
    the name the CLI itself derives from its config directory."""
    spec = row.spec or {}
    service = spec.get("keychain")
    if not service:
        return None
    if row.profile == "@default":
        home_env = row.ctx.kind.cli.get("home_env") if row.ctx is not None else None
        configured = row.ctx.env.get(home_env) if home_env else None
        return _suffixed(service, configured) if configured and spec.get("keychain_profile") else service
    if not spec.get("keychain_profile") or row.ctx is None or not row.ctx.profile_dir:
        return None
    return _suffixed(service, row.ctx.profile_dir)


def _suffixed(service, directory):
    return "%s-%s" % (service, hashlib.sha256(directory.encode("utf-8")).hexdigest()[:8])


def read_keychain(row, env):
    """macOS Keychain fallback for a spec that names a service (see
    keychain_service). Returns parsed JSON, None (nothing to read here), or
    Failure. The secret is parsed and dropped; it is never printed or logged."""
    if not (row.spec or {}).get("keychain") or os_name() != "macos" or env.get("AGENTKIT_KEYCHAIN") == "off":
        return None     # AGENTKIT_KEYCHAIN=off: never touch the Keychain (the test suite sets it)
    service = keychain_service(row)
    if service is None:
        return Failure("no_login", "the login of this profile is in the macOS Keychain; ak cannot read per-profile entries",
                       short="login in the Keychain; not readable")
    security = common.which("security", env)
    if not security:
        return None
    clean = {k: v for k, v in env.items() if not common.secret_like(k)}
    try:
        proc = subprocess.run([security, "find-generic-password", "-s", service, "-w"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=10, env=clean)
    except subprocess.TimeoutExpired:
        return Failure("no_login", "the macOS Keychain did not answer; unlock it and retry", short="unlock the Keychain")
    except OSError:
        return None
    if proc.returncode == 44:       # errSecItemNotFound
        return None
    if proc.returncode != 0:
        return Failure("no_login", "macOS Keychain access was denied or is unavailable", short="Keychain access denied")
    try:
        return json.loads(proc.stdout.decode("utf-8-sig"))
    except ValueError:
        return Failure("error", "the Keychain item is not valid JSON")


def evaluate(row, env, timeout, now):
    """One row -> its result dict. Never raises for a row-level problem."""
    if row.unsupported:
        result = _result(row, "unsupported", reason=row.unsupported, short=row.short)
        if row.connected is not None:
            result["connected"] = bool(row.connected)
            result["_how"] = row.how
        return result
    adapter = ADAPTERS.get(row.source)
    if adapter is None:
        return _result(row, "error", error="no parser for this source in this version")
    cred = credential_of(row, env, adapter)
    if isinstance(cred, Failure):
        if cred.status == "unsupported":
            return _result(row, "unsupported", reason=cred.message, short=cred.short)
        return _result(row, cred.status, error=cred.message, short=cred.short)
    if cred.expires_at is not None and cred.expires_at <= now:
        return _result(row, "expired", error="the login has expired; open this profile once to renew it",
                       short="open %s once to renew" % _launch_hint(row))
    if adapter.required_scope and cred.scopes is not None and adapter.required_scope not in cred.scopes:
        return _result(row, "no_scope", error="the login lacks the %s permission; sign in again with a full login"
                       % adapter.required_scope, short="sign in again (full login)")
    url = resolve_url(row, env)
    headers = {k: v.replace("{token}", cred.token) for k, v in row.spec["headers"].items()}
    headers.setdefault("user-agent", "agentkit/%s" % common.VERSION)
    seconds = request_timeout(row, timeout)
    try:
        status, body = http_get(url, headers, seconds)
    except HttpFailure as exc:
        return _result(row, "error", error=str(exc))
    if status in (301, 302, 303, 307, 308):
        return _result(row, "error", error="unexpected redirect")
    if status in (401, 403):
        return _result(row, "no_scope", error="the login was rejected (HTTP %d); sign in again with a full login" % status,
                       short="login rejected; sign in again")
    if status == 429:
        return _result(row, "rate_limited", error="rate limited (HTTP 429); try again later", short="try again later")
    if status != 200:
        return _result(row, "error", error="HTTP %d" % status)
    if len(body) > MAX_BODY:
        return _result(row, "error", error="response too large")
    try:
        doc = json.loads(body.decode("utf-8-sig"))
        plan, windows = adapter.parse(doc)
    except NoQuota as exc:
        return _result(row, "unsupported", reason=str(exc), short="no limits reported")
    except (ValueError, ShapeError) as exc:
        detail = " (%s)" % exc.__class__.__name__ if env.get("AGENTKIT_DEBUG") == "1" else ""
        return _result(row, "error", error="unexpected response shape" + detail)
    result = _result(row, "ok", plan=plan or cred.plan, windows=windows)
    try:
        result.update({k: v for k, v in adapter.extras(doc).items() if k in ROW_EXTRAS and v is not None})
    except Exception:
        pass
    return result


def request_timeout(row, override):
    if override:
        return min(int(override), MAX_TIMEOUT)
    table = row.spec.get("timeout_s", DEFAULT_TIMEOUT) if row.spec else DEFAULT_TIMEOUT
    return min(int(table), MAX_TIMEOUT)


def _safe_evaluate(row, env, timeout, now):
    try:
        return evaluate(row, env, timeout, now)
    except AkError:
        raise
    except Exception as exc:
        return _result(row, "error", error="internal error (%s)" % exc.__class__.__name__)


def fetch_all(rows, env, timeout, now):
    """Evaluate every row concurrently (at most MAX_WORKERS in flight) and
    return the results in row order. One row's failure never affects another.
    Workers are daemon threads and an overall deadline bounds the wait, so a
    stuck socket cannot hold the process."""
    results = [None] * len(rows)
    refusal = []
    cursor = [0]
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if cursor[0] >= len(rows):
                    return
                index = cursor[0]
                cursor[0] += 1
            try:
                results[index] = _safe_evaluate(rows[index], env, timeout, now)
            except AkError as exc:
                refusal.append(exc)
                results[index] = _result(rows[index], "error", error="refused")

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(MAX_WORKERS, len(rows)))]
    for thread in threads:
        thread.start()
    longest = max([request_timeout(r, timeout) for r in rows] or [DEFAULT_TIMEOUT])
    import time
    deadline = time.time() + longest + 5
    for thread in threads:
        thread.join(max(0.0, deadline - time.time()))
    if refusal:
        raise refusal[0]
    for index, row in enumerate(rows):
        if results[index] is None:
            results[index] = _result(row, "error", error="timed out after %ds" % request_timeout(row, timeout))
    return results


def fetch_cached(rows, env, timeout, now, max_age):
    """fetch_all, but a row with a fresh usage-cache entry (age <= max_age)
    is answered from the cache; every live result refreshes the cache.
    Results carry `_source` (cache|live) and `_age` (seconds)."""
    results = [None] * len(rows)
    live = []
    for index, row in enumerate(rows):
        cached, age = state.cache_get(env, row.cli, row.profile, now, max_age)
        if cached is None:
            live.append(index)
            continue
        cached.update({"_source": "cache", "_age": age})
        results[index] = cached
    fetched = fetch_all([rows[i] for i in live], env, timeout, now) if live else []
    for index, result in zip(live, fetched):
        state.cache_put(env, result, now)
        result.update({"_source": "live", "_age": 0})
        results[index] = result
    return results


# --------------------------------------------------------------- adapters

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShapeError("not a number")
    return value


def _epoch_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 1000.0 if value > 1e11 else float(value)


class AnthropicOAuth(Adapter):
    """Claude Code subscription: GET /api/oauth/usage with the login's
    access token. Windows are the provider's own (5-hour, weekly, per-model
    weekly). Assumption A1 (to confirm on real accounts): utilization is a
    percentage 0..100."""

    id = "anthropic-oauth"
    required_scope = "user:profile"
    WINDOWS = (("five_hour", "5h", "5-hour", 18000),
               ("seven_day", "7d", "7-day all models", 604800),
               ("seven_day_opus", "7d-opus", "7-day Opus only", 604800),
               ("seven_day_sonnet", "7d-sonnet", "7-day Sonnet only", 604800))

    def credential_from_file(self, doc):
        oauth = doc.get("claudeAiOauth") if isinstance(doc, dict) and isinstance(doc.get("claudeAiOauth"), dict) else doc
        token = oauth.get("accessToken") if isinstance(oauth, dict) else None
        if not isinstance(token, str) or not token:
            return Failure("no_login", "the login file holds no subscription login (API-key logins have no quota to read)")
        scopes = oauth.get("scopes")
        plan = oauth.get("subscriptionType")
        return Credential(token, _epoch_seconds(oauth.get("expiresAt")),
                          scopes if isinstance(scopes, list) and all(isinstance(x, str) for x in scopes) else None,
                          plan if isinstance(plan, str) and plan else None)

    def parse(self, doc):
        if not isinstance(doc, dict):
            raise ShapeError("not an object")
        windows = []
        for key, wid, label, seconds in self.WINDOWS:
            entry = doc.get(key)
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ShapeError("window is not an object")
            used = _number(entry.get("utilization"))
            windows.append(window(wid, label, used, parse_time(entry.get("resets_at")), seconds))
        windows.extend(self._limits(doc.get("limits"), {w["id"] for w in windows}))
        if not windows:
            raise ShapeError("no known window")
        return None, windows

    # An unscoped weekly limit covers every model; a scoped one only its model,
    # so the labels say which ("7-day all models" next to "7-day Fable only").
    GROUPS = {"session": ("5h", "5-hour", 18000), "weekly": ("7d", "7-day all models", 604800)}

    def _limits(self, limits, seen):
        """The newer `limits` list: one entry per limit, with a group
        (session, weekly), a percent and an optional model scope. A plan
        without a global weekly cap (Team, Enterprise) reports its per-model
        weekly limits only here. Entries that repeat a legacy window are
        skipped; an entry without a percent is not a window."""
        windows = []
        for entry in limits if isinstance(limits, list) else []:
            if not isinstance(entry, dict):
                continue
            pct = entry.get("percent")
            if isinstance(pct, bool) or not isinstance(pct, (int, float)):
                continue
            group = str(entry.get("group") or entry.get("kind") or "limit")
            wid, label, seconds = self.GROUPS.get(group, (None, group.replace("_", " "), None))
            wid = wid or (re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-") or "limit")
            scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            name = model.get("display_name") or model.get("id")
            if isinstance(name, str) and name:
                wid = "%s-%s" % (wid, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))
                label = "%s %s only" % (label.replace(" all models", ""), clean_text(name, 20))
            if wid in seen:
                continue
            seen.add(wid)
            windows.append(window(wid, label, pct, parse_time(entry.get("resets_at")), seconds))
        return windows


register(AnthropicOAuth())


def _jwt_claims(token):
    """The claims of a JWT (not verified; read only for expiry and plan), or {}."""
    import base64
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part.encode("ascii")).decode("utf-8"))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


class ChatGPTWham(Adapter):
    """Codex with a ChatGPT login: GET /backend-api/wham/usage. The primary
    window is the session (5-hour) window, the secondary the weekly one;
    additional named limits are reported as windows of their own. Field names
    inside a window are assumption A3 (to confirm on real accounts); a changed
    shape degrades to an error row. An API-key login has no subscription quota
    and is reported unsupported. Tokens are never refreshed: Codex refreshes
    its own login."""

    id = "chatgpt-wham"

    def credential_from_file(self, doc):
        tokens = doc.get("tokens") if isinstance(doc, dict) and isinstance(doc.get("tokens"), dict) else {}
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            if isinstance(doc, dict) and doc.get("OPENAI_API_KEY"):
                return Failure("unsupported", "an API-key login has no subscription quota to read")
            return Failure("no_login", "the login file holds no ChatGPT login")
        plan = None
        id_token = tokens.get("id_token")
        if isinstance(id_token, str):
            auth = _jwt_claims(id_token).get("https://api.openai.com/auth")
            if isinstance(auth, dict) and isinstance(auth.get("chatgpt_plan_type"), str):
                plan = auth["chatgpt_plan_type"]
        exp = _jwt_claims(access).get("exp")
        return Credential(access, float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None,
                          None, plan)

    @staticmethod
    def _window(entry, wid, label, default_seconds):
        if not isinstance(entry, dict):
            raise ShapeError("window is not an object")
        used = _number(entry.get("used_percent"))
        seconds = entry.get("limit_window_seconds")
        seconds = int(seconds) if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else default_seconds
        reset = parse_time(entry.get("reset_at"))
        after = entry.get("reset_after_seconds")
        if reset is None and isinstance(after, (int, float)) and not isinstance(after, bool):
            import time
            reset = iso_utc(time.time() + after)
        return window(wid, label, used, reset, seconds)

    def parse(self, doc):
        if not isinstance(doc, dict):
            raise ShapeError("not an object")
        limits = doc.get("rate_limit")
        if not isinstance(limits, dict):
            raise ShapeError("no rate_limit")
        windows = []
        if limits.get("primary_window") is not None:
            windows.append(self._window(limits["primary_window"], "5h", "5-hour", 18000))
        if limits.get("secondary_window") is not None:
            windows.append(self._window(limits["secondary_window"], "7d", "7-day", 604800))
        extra = doc.get("additional_rate_limits")
        for item in extra if isinstance(extra, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("limit_name") or item.get("name") or "extra"
            slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "extra"
            inner = item.get("rate_limit") if isinstance(item.get("rate_limit"), dict) else item
            if inner.get("primary_window") is not None:
                windows.append(self._window(inner["primary_window"], slug, "%s 5-hour" % name, 18000))
            if inner.get("secondary_window") is not None:
                windows.append(self._window(inner["secondary_window"], slug + "-7d", "%s 7-day" % name, 604800))
        if not windows:
            raise ShapeError("no known window")
        plan = doc.get("plan_type")
        return (plan if isinstance(plan, str) and plan else None), windows

    def extras(self, doc):
        """`rate_limit_reset_credits.available_count`: the limit resets the
        account holds (Codex spends one with /usage)."""
        credits = doc.get("rate_limit_reset_credits") if isinstance(doc, dict) else None
        count = credits.get("available_count") if isinstance(credits, dict) else None
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return {}
        return {"resets_available": count}


register(ChatGPTWham())


class ZaiQuota(Adapter):
    """Z.AI GLM coding plan: GET /api/monitor/usage/quota/limit with the
    profile's API key (credential = env, resolved by the pipeline). Each
    limit entry is a window of its own: TOKENS_LIMIT and CREDIT_LIMIT are the
    coding-plan windows, TIME_LIMIT the MCP window. percentage is 0..100
    (assumption A5); nextResetTime is epoch milliseconds. An empty or
    unrecognised list means nothing to show, never 0 %."""

    id = "zai-quota"
    TYPES = {"TOKENS_LIMIT": ("tokens", "Tokens"), "CREDIT_LIMIT": ("credits", "Credits"), "TIME_LIMIT": ("mcp", "MCP")}
    PLAN_KEYS = ("planName", "plan", "plan_type", "packageName", "level")

    def credential_from_file(self, doc):
        return Failure("error", "this source reads an API key from the environment")

    @staticmethod
    def _percent(entry):
        value = entry.get("percentage")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        total = entry.get("usage")
        if isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
            current, remaining = entry.get("currentValue"), entry.get("remaining")
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                return current * 100.0 / total
            if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
                return (total - remaining) * 100.0 / total
        return None

    # `unit` + `number` give a limit's period: unit 3 is hours (number 5 = the
    # 5-hour window), unit 6 is weeks (number 1 = the weekly window). Other
    # units are not confirmed, so such a limit keeps its type label.
    UNITS = {3: (3600, "%dh", "%d-hour", 1), 6: (604800, "%dd", "%d-day", 7)}
    # The coding-plan windows are named by their period alone, like the other
    # CLIs' (5-hour, 7-day); any other type keeps its name in front (MCP 1-month).
    PLAN_TYPES = ("TOKENS_LIMIT", "CREDIT_LIMIT")

    @staticmethod
    def _whole(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0

    def _period(self, entry):
        unit, number = entry.get("unit"), entry.get("number")
        if isinstance(unit, bool) or not isinstance(number, int) or isinstance(number, bool) or number < 1:
            return None
        spec = self.UNITS.get(unit)
        if spec is None:
            return None
        seconds, wid, label, scale = spec
        return wid % (number * scale), label % (number * scale), seconds * number

    def parse(self, doc):
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("limits", []), list):
            raise ShapeError("no data.limits")
        plan = next((data[k] for k in self.PLAN_KEYS if isinstance(data.get(k), str) and data[k]), None)
        windows, seen = [], {}
        for entry in data.get("limits", []):
            if not isinstance(entry, dict):
                raise ShapeError("limit is not an object")
            pct = self._percent(entry)
            if pct is None:
                continue
            kind = entry.get("type")
            wid, label = self.TYPES.get(kind, (re.sub(r"[^a-z0-9]+", "-", str(kind).lower()).strip("-") or "limit", str(kind)))
            unit_name = wid
            period = self._period(entry)
            seconds = None
            if period is not None:
                pid, plabel, seconds = period
                if kind in self.PLAN_TYPES:
                    wid, label = pid, plabel
                else:
                    wid, label = "%s-%s" % (wid, pid), "%s %s" % (label, plabel)
            seen[wid] = seen.get(wid, 0) + 1
            if seen[wid] > 1:
                wid, label = "%s-%d" % (wid, seen[wid]), "%s (%d)" % (label, seen[wid])
            used, limit = entry.get("currentValue"), entry.get("usage")
            amount = (used, limit, unit_name) if kind in self.PLAN_TYPES and self._whole(used) and self._whole(limit) \
                and limit > 0 else None
            windows.append(window(wid, label, pct, parse_time(entry.get("nextResetTime")), seconds, amount))
        if not windows:
            raise NoQuota("the plan reports no limits")
        return plan, windows


register(ZaiQuota())


# ------------------------------------------------------------- rendering

def _relative(iso, now):
    if not iso:
        return "-"
    delta = int(epoch_of(iso) - now)
    if delta <= 0:
        return "reset due"
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return "in %dd %dh" % (days, hours)
    if hours:
        return "in %dh %dm" % (hours, minutes)
    return "in %dm" % max(minutes, 1)


def _amount(value):
    """3265 -> 3.27K, 12000 -> 12K, 1500000 -> 1.5M (the vendor's own style)."""
    for scale, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= scale:
            return ("%.2f" % (value / scale)).rstrip("0").rstrip(".") + suffix
    return ("%.2f" % value).rstrip("0").rstrip(".")


BAR_CELLS = 10
EIGHTHS = "▏▎▍▌▋▊▉"


def _bar(pct, utf8):
    """A fixed-width bar. Any nonzero use is visible (1% is never an empty
    bar) and anything below 100 is never drawn full. UTF-8 has eighth-cell
    precision; ASCII has whole cells of '#'."""
    pct = max(0.0, min(100.0, float(pct)))
    if not utf8:
        filled = int(round(pct / 10.0))
        if pct > 0:
            filled = max(1, filled)
        if pct < 100:
            filled = min(BAR_CELLS - 1, filled)
        return "#" * filled + "-" * (BAR_CELLS - filled)
    eighths = int(round(pct * BAR_CELLS * 8 / 100.0))
    if pct > 0:
        eighths = max(1, eighths)
    if pct < 100:
        eighths = min(BAR_CELLS * 8 - 1, eighths)
    full, part = divmod(eighths, 8)
    bar = "█" * full + (EIGHTHS[part - 1] if part else "")
    return bar + "░" * (BAR_CELLS - len(bar))


STATUS_LABELS = {"expired": "expired", "no_login": "no login", "no_scope": "no access",
                 "rate_limited": "rate limited", "error": "error"}
NOTE_MIN = 16         # a note is never squeezed below this many characters
INDENT = 2            # accounts sit under their CLI's title line
RESET_HINT = "resets: use one with /usage in codex"


def _paint(text, code, color):
    return "\x1b[%sm%s\x1b[0m" % (code, text) if color and text else text


def _fit(text, room):
    """One line of at most `room` visible characters, with an ellipsis."""
    if room is None or len(text) <= room:
        return text
    return text[:max(room - 1, 1)].rstrip(" ;,") + "\u2026"


def _note(r, verbose):
    full = r["reason"] if r["status"] == "unsupported" else r["error"]
    return (full or "") if verbose else (r.get("_short") or full or "")


def render_table(results, platform, color, now, verbose=False, names=None):
    """The human table, one block per CLI or provider: a title line
    (`claude · Claude Code`), its accounts indented under one shared header,
    and a blank line between blocks. Without -v it fits the terminal: rows
    with no readable quota (n/d) fold into one closing line grouped by cause,
    and a problem row shows its status and a few-word note. -v lists every
    row with its full note. Pipes and files are never cut (no width).
    names: {cli or provider id: display name} for the titles."""
    utf8 = platform.utf8_stdout()
    width = None if verbose else platform.columns
    names = names or {}
    every_nd = all(r["status"] == "unsupported" for r in results)
    fold = not verbose and not every_nd
    groups, folded = [], []          # [(cli, [(cells, note)], hint)]
    linked = []                      # n/d but connected: listed at the very end
    for r in results:
        if r["status"] == "unsupported" and fold:
            (linked if r.get("connected") else folded).append(r)
            continue
        if not groups or groups[-1][0] != r["cli"]:
            groups.append((r["cli"], [], []))
        lines, hints = groups[-1][1], groups[-1][2]
        base = [r["profile"] + (" (ak %s)" % r["cli"] if r.get("default") else ""), r["plan"] or "-"]
        if r["status"] == "ok" and r["windows"]:
            for i, w in enumerate(r["windows"]):
                pct = w["used_pct"]
                used = "-" if pct is None else "%s %3d%%" % (_bar(pct, utf8), round(pct))
                if pct is not None:
                    used = _paint(used, "31" if pct >= 90 else ("33" if pct >= 70 else "32"), color)
                head = base if i == 0 else ["", ""]
                reset = _relative(w["resets_at"], now)
                if w.get("limit"):
                    unit = " " + w["unit"] if verbose and w.get("unit") else ""
                    reset = "%-9s  %s/%s%s" % (reset, _amount(w["used"]), _amount(w["limit"]), unit)
                lines.append((head + [w["label"], used], reset.rstrip()))
            if r.get("resets_available"):
                lines.append((["", "", "resets"], "%d available" % r["resets_available"]))
                if r["cli"] == "codex" and RESET_HINT not in hints:
                    hints.append(RESET_HINT)
        elif r["status"] == "ok":
            lines.append((base + ["-"], "no windows reported"))
        elif r["status"] == "unsupported":
            how = (r.get("_how") or "") + (": " if r.get("_how") else "")
            lines.append((base + [_paint("n/d", "2", color)], how + _note(r, verbose)))
        else:
            label = STATUS_LABELS.get(r["status"], r["status"])
            lines.append((base + [_paint(label, "31" if r["status"] == "error" else "33", color)], _note(r, verbose)))
    header = (["PROFILE", "PLAN", "WINDOW", "USED"], "RESET")
    rows = [header] + [line for _cli, lines, _h in groups for line in lines]
    # A row without windows has no USED cell: its note starts in that column.
    widths = [max(len(_visible(c[i])) for c, _n in rows if len(c) > i) for i in range(4)]

    def render(cells, note):
        padded = [c + " " * (w - len(_visible(c))) for c, w in zip(cells, widths)]
        lead = INDENT + sum(widths[:len(cells)]) + 2 * len(cells)
        room = max(width - lead, NOTE_MIN) if width else None
        return (" " * INDENT + "  ".join(padded + [_fit(note, room)])).rstrip()

    out = [_paint(render(*header), "2", color)]
    for cli, lines, hints in groups:
        out.append("")
        title = _paint(cli, "1", color)
        if names.get(cli) and names[cli].lower() != cli:
            title += _paint((" \u00b7 " if utf8 else " - ") + names[cli], "2", color)
        if hints:
            title += _paint("   " + "; ".join(hints), "2", color)
        out.append(title)
        out.extend(render(cells, note) for cells, note in lines)
    if linked:
        out.append("")
        out.extend(_linked_lines(linked, width, color, utf8))
    if folded:
        out.append("")
        out.extend(_folded_lines(folded, width, color))
    return "\n".join(out) + "\n"


def _linked_lines(rows, width, color, utf8):
    """The accounts that are connected (a login or a key) but expose no quota
    to read: still worth seeing, so they close the table in a block of their
    own — CLI, profile, how it is connected, why there is no number."""
    sep = " \u00b7 " if utf8 else " - "
    cells = [(r["cli"], r["profile"], r.get("_how") or "connected", _note(r, False)) for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(3)]
    out = [_paint("connected", "1", color) + _paint(sep + "no quota to read", "2", color)]
    for cli, profile, how, note in cells:
        lead = " " * INDENT + "  ".join(v + " " * (w - len(v)) for v, w in zip((cli, profile, how), widths))
        room = max(width - len(lead) - 2, NOTE_MIN) if width else None
        out.append((lead + "  " + _paint(_fit(note, room), "2", color)).rstrip())
    return out


def display_names(model):
    """{cli or provider id: its human name} for the block titles."""
    names = {c: d.get("name") for c, d in model.clis.items()}
    names.update({p: d.get("name") for p, d in model.providers.items()})
    return {k: v for k, v in names.items() if v}


def _folded_lines(rows, width, color):
    """`n/d  cursor (web session only) · grok (per-session only)`, wrapped
    to the terminal, grouped by note so CLIs that share a cause share it."""
    groups = []
    for r in rows:
        who = r["cli"] if r["profile"] == "@default" else "%s %s" % (r["cli"], r["profile"])
        note = _note(r, False)
        for entry in groups:
            if entry[0] == note:
                entry[1].append(who)
                break
        else:
            groups.append([note, [who]])
    parts = ["%s (%s)" % (", ".join(names), note) if note else ", ".join(names) for note, names in groups]
    prefix, indent = "n/d  ", "     "
    lines, current = [], ""
    limit = width or 0
    for part in parts:
        candidate = part if not current else current + " \u00b7 " + part
        if limit and current and len(prefix) + len(candidate) > limit:
            lines.append(current)
            current = part
        else:
            current = candidate
    lines.append(current)
    lines = [(prefix if i == 0 else indent) + _fit(line, (limit - len(prefix)) if limit else None)
             for i, line in enumerate(lines)]
    lines.append(_paint(indent + "ak usage -v for every row and its reason", "2", color))
    return [_paint(line, "2", color) if i < len(lines) - 1 else line for i, line in enumerate(lines)]


def _visible(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def mark_defaults(model, results, env):
    """Flag (`default: true`, additive) the row a bare `ak <cli>` launches
    when AGENTKIT_DEFAULT_PROFILE_<CLI> is set: the named profile, or for
    `pick` the portable-login account `ak pick`'s policy ranks first among
    these results. A row of a provider key is never flagged. An invalid
    setting flags nothing (ak doctor names it)."""
    if not any(k.startswith(profiles.DEFAULT_PREFIX) and env.get(k) for k in env):
        return results
    import pick
    for cli_name in _cli_order(model):
        try:
            setting = profiles.default_setting(cli_name, env)
        except AkError:
            continue
        if setting is None:
            continue
        own = [r for r in results if r["cli"] == cli_name]
        if setting == profiles.PICK:
            pool = [r for r in own if profiles.portable_login(model, cli_name, profiles._name_of(r["profile"]), env)]
            clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in pool]
            chosen = pick.choose(clean, allow_unknown=True, now=common_now())[0]
            target = chosen[0]["profile"] if chosen else None
        else:
            target = profiles.label(setting)
        for r in own:
            if r["profile"] == target:
                r["default"] = True
    return results


def render_json(results, now):
    stamp = iso_utc(now)
    rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]   # _short, _how: table only
    doc = {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": stamp, "rows": rows}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ------------------------------------------------------------------ main

def parse_args(args):
    opts = {"target": None, "profile": None, "json": False, "timeout": None, "color": True, "verbose": False}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--no-color":
            opts["color"] = False
        elif arg in ("-v", "--verbose"):
            opts["verbose"] = True
        elif arg == "--timeout":
            i += 1
            if i >= len(args) or not args[i].isdigit() or not 1 <= int(args[i]) <= MAX_TIMEOUT:
                raise AkError("--timeout needs a number of seconds from 1 to %d" % MAX_TIMEOUT)
            opts["timeout"] = int(args[i])
        elif arg.startswith("-"):
            raise AkError("unknown option '%s'. See: ak usage --help" % arg)
        elif arg.startswith("@"):
            if opts["profile"] is not None:
                raise AkError("only one @profile can be given")
            opts["profile"] = _profile_label(profiles.normalize(arg[1:]))
        else:
            if opts["target"] is not None:
                raise AkError("only one kind or CLI can be given")
            opts["target"] = arg
        i += 1
    return opts


def emit(stream, text):
    """Write text to a console without ever failing on its encoding: a legacy
    console (cp1252 on Windows) gets '?' for what it cannot show."""
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))


def main(model, args, env, now=None, stdout=None, platform=None):
    stdout = stdout or sys.stdout
    opts = parse_args(args)
    if opts.get("help"):
        emit(stdout, USAGE)
        return EXIT_OK
    now = common_now() if now is None else now
    platform = platform or Platform.current(env, stdout)
    rows = filter_rows(model, enumerate_rows(model, env), opts["target"], opts["profile"])
    if not rows:
        hint = "no profile or login matches. Try: ak profiles"
        provider = model.kinds.get(opts["target"] or "", {}).get("provider")
        if provider and model.provider_usage(provider) and opts["profile"]:
            base = model.providers[provider]["key"]
            suffix = "" if opts["profile"] == "@default" else "_" + profiles.suffix(opts["profile"][1:])
            hint = "%s%s is not set, so there is no %s account for %s" % (base, suffix, provider, opts["profile"])
        common.warn("nothing to report: " + hint)
        if opts["json"]:
            emit(stdout, render_json([], now))
        return EXIT_NOTHING
    results = fetch_all(rows, env, opts["timeout"], now)
    for result in results:          # always live; refreshes what ak capacity / ak pick read
        state.cache_put(env, result, now)
    results = mark_defaults(model, results, env)
    if opts["json"]:
        emit(stdout, render_json(results, now))
    else:
        emit(stdout, render_table(results, platform, platform.supports_color(not opts["color"]), now,
                                          verbose=opts["verbose"], names=display_names(model)))
    return EXIT_PROBLEM if any(r["status"] in PROBLEM_STATUSES for r in results) else EXIT_OK


def common_now():
    import time
    return time.time()
