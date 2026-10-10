"""`ak usage [<kind-or-cli>] [@profile] [--json] [--timeout SECONDS] [--no-color]`
— the quota and usage of every account the kit can see, one row per
credential identity.

The sources are data (`[clis.<cli>.usage]` / `[providers.<id>.usage]` in
providers.toml); only the parsing of a response is code (an Adapter). The
endpoints are vendor-internal and unofficial: a changed shape is reported as
an `error` row, never a crash.

Secret discipline: a token lives in memory and in one request header. It is
never in a message, a log, the table, `--json` or a file. Nothing is
refreshed and nothing is written under a profile or the env file.

Portable on purpose (Linux, macOS, Windows): os.path, urllib, threads and
subprocess only; the few OS decisions sit in `Platform`.
"""

import datetime
import json
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
from common import AkError, EXIT_OK, EXIT_USAGE

SCHEMA = "usage-v1"
EXIT_PROBLEM = 1      # at least one row is not ok / unsupported
EXIT_NOTHING = 3      # nothing to report for the requested filter

STATUSES = ("ok", "expired", "no_login", "no_scope", "rate_limited", "unsupported", "error")
PROBLEM_STATUSES = ("expired", "no_login", "no_scope", "rate_limited", "error")

DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 60
MAX_BODY = 1 << 20    # 1 MiB
MAX_WORKERS = 8
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")

USAGE = """usage: ak usage [<kind-or-cli>] [@profile] [--json] [--timeout SECONDS] [--no-color]
Quota and usage of each account the kit can see (read-only; no token is printed,
refreshed or written). The sources are vendor-internal and unofficial.
"""


# ------------------------------------------------------------- platform

class Platform(object):
    """The few OS decisions of the command, injectable so tests can simulate
    Linux, macOS and Windows on any host."""

    def __init__(self, name=None, is_tty=False, encoding="utf-8", env=None):
        self.name = name or common.os_name()
        self.is_tty = is_tty
        self.encoding = (encoding or "ascii").lower()
        self.env = env if env is not None else {}

    @classmethod
    def current(cls, env, stream=None):
        stream = stream or sys.stdout
        try:
            tty = bool(stream.isatty())
        except (AttributeError, ValueError):
            tty = False
        return cls(common.os_name(), tty, getattr(stream, "encoding", None) or "ascii", env)

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

    def __init__(self, status, message):
        assert status in STATUSES and status != "ok"
        self.status = status
        self.message = message


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


ADAPTERS = {}


def register(adapter):
    ADAPTERS[adapter.id] = adapter
    return adapter


def window(wid, label, used_pct, resets_at, window_seconds):
    """One window of a row (usage-v1). used_pct is clamped to 0..100."""
    if used_pct is not None:
        used_pct = max(0.0, min(100.0, float(used_pct)))
        used_pct = int(used_pct) if used_pct == int(used_pct) else round(used_pct, 1)
    return {"id": wid, "label": label, "used_pct": used_pct, "resets_at": resets_at,
            "window_seconds": window_seconds}


def iso_utc(epoch_seconds):
    return datetime.datetime.fromtimestamp(int(epoch_seconds), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value):
    """An ISO-8601 string, or epoch seconds/milliseconds, -> ISO UTC string
    (or None when it is not a time)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return iso_utc(seconds)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{9,13}(\.\d+)?", text):
            return parse_time(float(text))
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

    def __init__(self, cli, profile, kind_names, spec, source, ctx=None, key_var=None, unsupported=None):
        self.cli = cli                    # CLI or provider id owning the credential
        self.profile = profile            # '@default' or '@name'
        self.kind_names = kind_names
        self.spec = spec                  # usage table (dict) or None
        self.source = source              # adapter id or 'none'
        self.ctx = ctx                    # kinds.Context for file credentials
        self.key_var = key_var            # env var holding the key (provider rows)
        self.unsupported = unsupported    # reason, for n/d rows


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
    for cli_name, name, _directory in profiles.listing(model, env):
        listing.setdefault(cli_name, []).append(name)
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
                row = Row(pname, label, kind_names, table, "none", unsupported=table["unsupported"])
            else:
                row = Row(pname, label, kind_names, table, table["adapter"], key_var=var)
            provider_rows.append(row)
            for kn in kind_names:
                covered.add((model.kinds[kn]["cli"], label))
    # subscription / harness rows
    for cli_name in _cli_order(model):
        table = model.cli_usage(cli_name)
        installed = _installed(model, env, cli_name)
        candidates = [None] if installed else []
        candidates.extend(sorted(listing.get(cli_name, [])))
        for name in candidates:
            label = _profile_label(name) if name else "@default"
            kind_names = [cli_name] if table is None else _kinds_of_cli(model, cli_name)
            if table is None:
                if (cli_name, label) in covered:
                    continue
                example = next((k for k in _kinds_of_cli(model, cli_name) if k != cli_name), None)
                hint = "; its usage shows up under the provider key of a kind such as %s" % example if example else ""
                rows.append(Row(cli_name, label, [cli_name], None, "none",
                                unsupported="%s has no usage source of its own%s" % (cli_name, hint)))
            elif "unsupported" in table:
                rows.append(Row(cli_name, label, kind_names, table, "none", unsupported=table["unsupported"]))
            else:
                rows.append(Row(cli_name, label, [cli_name], table, table["adapter"],
                                ctx=_context(model, env, cli_name, name)))
    return _order(rows + provider_rows, model)


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


def http_get(url, headers, timeout):
    """One GET: no redirect followed, body capped. -> (status, bytes).
    A failure carries a message built from the exception class only."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
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

def _result(row, status, plan=None, windows=None, error=None, reason=None):
    return {"cli": row.cli, "profile": row.profile, "kinds": list(row.kind_names), "plan": plan, "status": status,
            "windows": windows or [], "source": row.source, "error": error, "reason": reason}


def _read_login_file(row):
    """First existing login file of the row's context -> parsed JSON, None
    (no file), or Failure."""
    for ref in row.spec.get("files", []):
        path = row.ctx.ref_path(ref)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as handle:
                return json.loads(handle.read().decode("utf-8-sig"))
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
        return Failure("no_login", "no login found for this profile")
    return adapter.credential_from_file(doc)


def os_name():
    """Indirection so tests can simulate another OS."""
    return common.os_name()


def read_keychain(row, env):
    """macOS Keychain fallback, only for a spec that names a service and only
    for the CLI's default home (the per-profile entry name is not verified,
    so a profile is reported honestly instead of guessed). Returns parsed
    JSON, None (nothing to read here), or Failure. The secret is parsed and
    dropped; it is never printed or logged."""
    service = (row.spec or {}).get("keychain")
    if not service or os_name() != "macos":
        return None
    if row.profile != "@default":
        return Failure("no_login", "the login of this profile is in the macOS Keychain; ak cannot read per-profile entries")
    security = common.which("security", env)
    if not security:
        return None
    clean = {k: v for k, v in env.items() if not common.secret_like(k)}
    try:
        proc = subprocess.run([security, "find-generic-password", "-s", service, "-w"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=10, env=clean)
    except subprocess.TimeoutExpired:
        return Failure("no_login", "the macOS Keychain did not answer; unlock it and retry")
    except OSError:
        return None
    if proc.returncode == 44:       # errSecItemNotFound
        return None
    if proc.returncode != 0:
        return Failure("no_login", "macOS Keychain access was denied or is unavailable")
    try:
        return json.loads(proc.stdout.decode("utf-8-sig"))
    except ValueError:
        return Failure("error", "the Keychain item is not valid JSON")


def evaluate(row, env, timeout, now):
    """One row -> its result dict. Never raises for a row-level problem."""
    if row.unsupported:
        return _result(row, "unsupported", reason=row.unsupported)
    adapter = ADAPTERS.get(row.source)
    if adapter is None:
        return _result(row, "error", error="no parser for this source in this version")
    cred = credential_of(row, env, adapter)
    if isinstance(cred, Failure):
        if cred.status == "unsupported":
            return _result(row, "unsupported", reason=cred.message)
        return _result(row, cred.status, error=cred.message)
    if cred.expires_at is not None and cred.expires_at <= now:
        return _result(row, "expired", error="the login has expired; open this profile once to renew it")
    if adapter.required_scope and cred.scopes is not None and adapter.required_scope not in cred.scopes:
        return _result(row, "no_scope", error="the login lacks the %s permission; sign in again with a full login"
                       % adapter.required_scope)
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
        return _result(row, "no_scope", error="the login was rejected (HTTP %d); sign in again with a full login" % status)
    if status == 429:
        return _result(row, "rate_limited", error="rate limited (HTTP 429); try again later")
    if status != 200:
        return _result(row, "error", error="HTTP %d" % status)
    if len(body) > MAX_BODY:
        return _result(row, "error", error="response too large")
    try:
        doc = json.loads(body.decode("utf-8-sig"))
        plan, windows = adapter.parse(doc)
    except NoQuota as exc:
        return _result(row, "unsupported", reason=str(exc))
    except (ValueError, ShapeError) as exc:
        detail = " (%s)" % exc.__class__.__name__ if env.get("AGENTKIT_DEBUG") == "1" else ""
        return _result(row, "error", error="unexpected response shape" + detail)
    return _result(row, "ok", plan=plan or cred.plan, windows=windows)


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
               ("seven_day", "7d", "7-day", 604800),
               ("seven_day_opus", "7d-opus", "7-day Opus", 604800),
               ("seven_day_sonnet", "7d-sonnet", "7-day Sonnet", 604800))

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
        if not windows:
            raise ShapeError("no known window")
        return None, windows


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
            seen[wid] = seen.get(wid, 0) + 1
            if seen[wid] > 1:
                wid, label = "%s-%d" % (wid, seen[wid]), "%s (%d)" % (label, seen[wid])
            windows.append(window(wid, label, pct, parse_time(entry.get("nextResetTime")), None))
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


def _bar(pct, utf8):
    full, empty = ("█", "░") if utf8 else ("#", "-")
    filled = int(round(pct / 10.0))
    return full * filled + empty * (10 - filled)


def render_table(results, platform, color, now):
    utf8 = platform.utf8_stdout()
    header = ("CLI", "PROFILE", "PLAN", "WINDOW", "USED", "RESET / NOTE")
    lines = []
    for r in results:
        base = [r["cli"], r["profile"], r["plan"] or "-"]
        if r["status"] == "ok" and r["windows"]:
            for i, w in enumerate(r["windows"]):
                used = "-" if w["used_pct"] is None else "%s %d%%" % (_bar(w["used_pct"], utf8), round(w["used_pct"]))
                pct = w["used_pct"]
                if color and pct is not None:
                    code = "31" if pct >= 90 else ("33" if pct >= 70 else "32")
                    used = "\x1b[%sm%s\x1b[0m" % (code, used)
                head = base if i == 0 else ["", "", ""]
                lines.append(head + [w["label"], used, _relative(w["resets_at"], now)])
        elif r["status"] == "ok":
            lines.append(base + ["-", "no windows reported", ""])
        elif r["status"] == "unsupported":
            lines.append(base + ["n/d", "", r["reason"] or ""])
        else:
            lines.append(base + [r["status"], "", r["error"] or ""])
    table = [header] + lines
    widths = [max(len(_visible(c)) for c in col) for col in zip(*table)]
    out = []
    for row in table:
        cells = [c + " " * (w - len(_visible(c))) for c, w in zip(row[:5], widths)]
        out.append("  ".join(cells + [row[5]]).rstrip())
    return "\n".join(out) + "\n"


def _visible(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def render_json(results, now):
    stamp = iso_utc(now)
    doc = {"schema": SCHEMA, "interface": common.INTERFACE, "generated_at": stamp, "rows": results}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ------------------------------------------------------------------ main

def parse_args(args):
    opts = {"target": None, "profile": None, "json": False, "timeout": None, "color": True}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--no-color":
            opts["color"] = False
        elif arg == "--timeout":
            i += 1
            if i >= len(args) or not args[i].isdigit() or not 1 <= int(args[i]) <= MAX_TIMEOUT:
                raise AkError("--timeout needs a number of seconds from 1 to %d" % MAX_TIMEOUT)
            opts["timeout"] = int(args[i])
        elif arg.startswith("--"):
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


def main(model, args, env, now=None, stdout=None, platform=None):
    stdout = stdout or sys.stdout
    opts = parse_args(args)
    if opts.get("help"):
        stdout.write(USAGE)
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
            stdout.write(render_json([], now))
        return EXIT_NOTHING
    results = fetch_all(rows, env, opts["timeout"], now)
    if opts["json"]:
        stdout.write(render_json(results, now))
    else:
        stdout.write(render_table(results, platform, platform.supports_color(not opts["color"]), now))
    return EXIT_PROBLEM if any(r["status"] in PROBLEM_STATUSES for r in results) else EXIT_OK


def common_now():
    import time
    return time.time()
