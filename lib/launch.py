"""`ak <kind> [@profile] [--auto] [-c | -r [id] | -l] [--] [cli args…]`.

The kit reads only the head of the arguments; everything after the first
token it does not own (or after `--`) reaches the CLI untouched:

  * `@name` is a profile only as the first non-`--auto` argument after the
    kind (AGENTKIT_PROFILE is the fallback; a positional profile wins);
  * `--auto` (anywhere in the head) adds the CLI's own autonomy flag;
  * one session flag: -c/--continue, -r/--resume [id], and -l/--last where
    the CLI defines it (Codex: continue; Cursor: list) — mapped per CLI
    from providers.toml;
  * `--` stops the kit from reading anything else.

prepare() is shared by launch, `ak run` and `ak env`: it resolves the kind,
the executable, the profile, the provider key and the environment.
"""

import json
import os
import subprocess
import sys

import common
import kinds
import profiles
import writers
from common import AkError, EXIT_NOT_READY, EXIT_USAGE

SESSION_FLAGS = {"-c": "continue", "--continue": "continue", "-r": "resume", "--resume": "resume"}
LAST_FLAGS = ("-l", "--last", "--list")


class Head(object):
    def __init__(self):
        self.profile_token = None
        self.profile_from_env = False
        self.auto = False
        self.session = None      # continue | resume | pick | list
        self.session_id = None
        self.passthrough = False
        self.rest = []


def parse_head(cli, args, env):
    head = Head()
    session = cli.get("session", {})
    i = 0
    n = len(args)
    seen_non_auto = False
    while i < n:
        tok = args[i]
        if tok == "--":
            head.passthrough = True
            i += 1
            break
        if tok == "--auto":
            head.auto = True
            i += 1
            continue
        if tok.startswith("@") and not seen_non_auto and head.profile_token is None:
            head.profile_token = tok
            seen_non_auto = True
            i += 1
            continue
        if head.session is None and tok in SESSION_FLAGS:
            seen_non_auto = True
            if SESSION_FLAGS[tok] == "continue":
                head.session = "continue"
                i += 1
            else:
                nxt = args[i + 1] if i + 1 < n else ""
                if nxt and not nxt.startswith("-"):
                    head.session, head.session_id = "resume", nxt
                    i += 2
                else:
                    head.session = "pick"
                    i += 1
            continue
        if head.session is None and tok in LAST_FLAGS and session.get("last"):
            seen_non_auto = True
            head.session = session["last"]
            i += 1
            continue
        break
    head.rest = list(args[i:])
    if head.profile_token is None and env.get("AGENTKIT_PROFILE"):
        head.profile_token = env["AGENTKIT_PROFILE"]
        if not head.profile_token.startswith("@"):
            head.profile_token = "@" + head.profile_token
        head.profile_from_env = True
    return head


def profile_name(head):
    if head.profile_token is None:
        return ""
    try:
        return profiles.normalize(head.profile_token[1:])
    except AkError as exc:
        if head.profile_from_env:
            exc.args = (str(exc) + " (the name came from AGENTKIT_PROFILE)",)
        raise


def permissions_mode(env):
    value = (env.get("AGENTKIT_PERMISSIONS") or "ask").strip().lower()
    if value not in ("ask", "auto"):
        raise AkError("AGENTKIT_PERMISSIONS must be 'ask' or 'auto' (got '%s')" % value, EXIT_USAGE)
    return value


class Prepared(object):
    """Everything a launch needs: the kind, executable, env and context."""

    def __init__(self, kind, exe, env, name, directory, ctx, auto):
        self.kind = kind
        self.exe = exe
        self.env = env
        self.profile = name
        self.directory = directory
        self.ctx = ctx
        self.auto = auto


def prepare(model, kind_name, head, base_env, purpose="launch"):
    """purpose: launch (may ask to create a profile), run (never asks),
    print (`ak env`: never needs or reads the key)."""
    kind = model.kind(kind_name)
    env = dict(base_env)
    exe = common.resolve_executable(kind.cli, env)
    if purpose != "print" and not exe:
        raise AkError("%s (%s) is not installed. Install it with: ak install %s"
                      % (kind.cli["name"], kind.executable, kind.cli_name), EXIT_NOT_READY)
    name = profile_name(head)
    if purpose == "launch":
        directory = profiles.ensure(kind.cli_name, name)
    else:
        directory = profiles.existing(kind.cli_name, name)
    if purpose == "print":
        profiles.apply_keys(kind, name, env, require=False)
    else:
        try:
            profiles.apply_keys(kind, name, env)
            key_error = None
        except AkError as exc:
            key_error = exc
        missing = kinds.missing_requirements(kind, env)
        if missing:
            needed = ([kind.key_var + ("_" + profiles.suffix(name) if name else "")] if key_error else []) + missing
            raise AkError("%s needs %s. Add %s to %s." % (kind.name, ", ".join(needed),
                          "them" if len(needed) > 1 else "it", common.env_file()), EXIT_NOT_READY)
        if key_error:
            raise key_error
    profiles.activate(kind.cli_name, kind.cli, name, directory, env)
    auto = head.auto or permissions_mode(env) == "auto"
    ctx = kinds.Context(kind, env, base_env.get("HOME") or common.home(), profile_dir=directory,
                        profile_label=profiles.label(name), allow_secret=(purpose != "print"))
    return Prepared(kind, exe, env, name, directory, ctx, auto)


def finish_env(model, prep):
    """Run the writer and export the kind's env (secrets included)."""
    if prep.kind.data.get("writer"):
        try:
            writers.apply(prep.kind, prep.ctx)
        except writers.WriterError as exc:
            raise AkError(str(exc), EXIT_NOT_READY)
    provider_env, _ = kinds.provider_env(prep.kind, prep.ctx, include_secret=True)
    prep.env.update(provider_env)
    profiles.strip_profile_keys(model, prep.env)
    # Autonomy is decided per launch and never inherited: a nested `ak` (a
    # sub-agent started by this agent) asks again unless it is told --auto
    # or reads AGENTKIT_PERMISSIONS=auto from the user's own env file.
    prep.env.pop("AGENTKIT_PERMISSIONS", None)


def cline_latest_session(prep):
    """Newest non-subagent Cline session started in this directory."""
    try:
        out = subprocess.run(common.windows_argv([prep.exe, "history", "--json", "--limit", "200"], prep.env), env=prep.env,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout
        rows = json.loads(out.decode("utf-8", "replace") or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if isinstance(rows, dict):
        rows = next((v for v in rows.values() if isinstance(v, list)), [])
    here = os.path.realpath(os.getcwd())
    best = None
    for row in rows:
        if not isinstance(row, dict) or row.get("isSubagent") or not row.get("sessionId"):
            continue
        cwd = row.get("cwd") or row.get("workspaceRoot") or ""
        if not cwd or os.path.realpath(cwd) != here:
            continue
        stamp = row.get("updatedAt") or row.get("endedAt") or row.get("startedAt") or ""
        if best is None or stamp > best[0]:
            best = (stamp, row["sessionId"])
    return best[1] if best else None


def session_args(prep, head):
    cli = prep.kind.cli
    session = cli.get("session", {})
    mode = head.session
    if mode is None:
        return []
    label = profiles.label(prep.profile)
    if mode == "continue" and "continue" not in session:
        if session.get("continue_strategy") == "cline-history":
            sid = cline_latest_session(prep)
            if not sid:
                raise AkError("no Cline session to continue in %s for %s. List them with: ak %s %s -r"
                              % (os.getcwd(), label, prep.kind.name, label), EXIT_NOT_READY)
            mode, head.session_id = "resume", sid
    if mode == "pick" and "pick" not in session:
        shown = label if prep.profile else ""
        message = session.get("pick_error", "%s has no session picker" % prep.kind.cli_name)
        message = message.replace("{kind}", prep.kind.name).replace("{profile}", shown).replace("  ", " ")
        raise AkError(message, EXIT_USAGE)
    template = session.get(mode)
    if template is None:
        raise AkError("%s does not support %s" % (prep.kind.cli_name, mode), EXIT_USAGE)
    ctx = prep.ctx
    ctx.specials["id"] = head.session_id or ""
    return ctx.expand_list(template)


def interactive_argv(prep, head):
    """The argv after the executable, in the CLI's own segment order."""
    cli = prep.kind.cli
    sess = session_args(prep, head)
    if head.session in cli.get("session", {}).get("standalone", []):
        return sess + head.rest, True
    segments = {
        "provider": prep.ctx.expand_list(prep.kind.data.get("args", [])),
        "session": sess,
        "auto": list(cli["auto"]) if prep.auto else [],
    }
    return prep.ctx.expand_list(cli["interactive"], segments) + head.rest, False


def run_pre(prep):
    pre = prep.kind.data.get("pre")
    if not pre:
        return
    argv = common.windows_argv([prep.exe] + prep.ctx.expand_list(pre), prep.env)
    try:
        # Its output goes to stderr: stdout belongs to the CLI (and to the
        # one JSON object of `ak run --output-format json`).
        status = subprocess.call(argv, env=prep.env, stdin=subprocess.DEVNULL, stdout=sys.stderr.fileno())
    except OSError as exc:
        raise AkError("%s %s failed to start: %s" % (prep.kind.executable, pre[0], exc.strerror), EXIT_NOT_READY)
    if status != 0:
        raise AkError("%s %s failed (exit %d)" % (prep.kind.executable, pre[0], status), EXIT_NOT_READY)


def launch(model, kind_name, args, base_env):
    kind = model.kind(kind_name)
    head = parse_head(kind.cli, args, base_env)
    prep = prepare(model, kind_name, head, base_env, purpose="launch")
    finish_env(model, prep)
    argv, standalone = interactive_argv(prep, head)
    if not standalone:
        run_pre(prep)
    return profiles.exec_command([prep.exe] + argv, prep.env)
