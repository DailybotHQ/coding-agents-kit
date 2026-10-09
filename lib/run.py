"""`ak run` — one prompt, non-interactively, then exit (interface 1).

    ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS]
           [--output-format text|json] [--auto] -- "<prompt>"

The per-CLI command line is data (providers.toml [clis.<cli>.run]):
    claude    claude -p "<prompt>" [--output-format json]
    codex     codex exec [--json] -C <cwd> "<prompt>"
    cursor    agent -p "<prompt>" [--output-format json] --trust
    opencode  opencode run [--format json] "<prompt>"
    pi        pi -p "<prompt>" [--mode json]
    cline     cline "<prompt>" [--json] -c <cwd> [-t <timeout>]
    grok      grok -p "<prompt>" [--output-format json] --cwd <cwd>
Provider kinds add their arguments; --auto (or AGENTKIT_PERMISSIONS=auto)
adds the CLI's autonomy flag for this run only.

Exit codes: 0 the agent finished and reported success; 1 it finished and
reported failure; 2 usage; 3 CLI not installed, not logged in, key or
profile missing; 4 timeout (process tree killed); 5 cancelled (SIGTERM or
SIGINT received; process tree killed); >= 64 kit internal error.

With --output-format json, stdout is exactly one JSON object — also when
the run never started — and the CLI's own output (its transcript) goes to
stderr:
    {"interface":1,"kind","profile","cwd","exit","duration_s",
     "result_text","cli_exit","truncated"}            (+ "error" on failure
                                                        to start)
"""

import collections
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time

import common
import launch
import profiles
from common import (AkError, EXIT_AGENT_FAILED, EXIT_CANCELLED, EXIT_INTERNAL, EXIT_NOT_READY, EXIT_OK,
                    EXIT_TIMEOUT, EXIT_USAGE)

RESULT_CAP = 64 * 1024          # result_text is cut at this many characters
CAPTURE_CAP = 8 * 1024 * 1024   # bytes of CLI stdout kept for extraction
KILL_GRACE = 3.0                # seconds between SIGTERM and SIGKILL

USAGE = ('usage: ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] '
         '[--output-format text|json] [--ask | --auto] -- "<prompt>"')


class Options(object):
    def __init__(self):
        self.kind = None
        self.profile_token = None
        self.cwd = None
        self.timeout = None
        self.fmt = "text"
        self.auto = False
        self.ask = False
        self.prompt = None


def parse(args, env):
    opts = Options()
    if not args or args[0].startswith("-"):
        raise AkError(USAGE, EXIT_USAGE)
    opts.kind = args[0]
    i = 1
    n = len(args)
    seen_dashdash = False
    while i < n:
        tok = args[i]
        if tok == "--":
            seen_dashdash = True
            i += 1
            break
        if tok.startswith("@") and opts.profile_token is None and i == 1:
            opts.profile_token = tok
        elif tok == "--auto":
            opts.auto = True
        elif tok == "--ask":
            opts.ask = True
        elif tok in ("--cwd", "--timeout", "--output-format"):
            if i + 1 >= n:
                raise AkError("%s needs a value. %s" % (tok, USAGE), EXIT_USAGE)
            value = args[i + 1]
            i += 1
            if tok == "--cwd":
                opts.cwd = value
            elif tok == "--timeout":
                try:
                    opts.timeout = float(value)
                except ValueError:
                    opts.timeout = -1
                if opts.timeout < 0 or not math.isfinite(opts.timeout):
                    raise AkError("--timeout takes a number of seconds (0 = none), got '%s'" % value, EXIT_USAGE)
                if opts.timeout == 0:
                    opts.timeout = None
            else:
                if value not in ("text", "json"):
                    raise AkError("--output-format is text or json, got '%s'" % value, EXIT_USAGE)
                opts.fmt = value
        else:
            raise AkError("unknown option '%s'. %s" % (tok, USAGE), EXIT_USAGE)
        i += 1
    if opts.auto and opts.ask:
        raise AkError("--ask and --auto contradict each other; pass one", EXIT_USAGE)
    if not seen_dashdash:
        raise AkError('the prompt goes after --. %s' % USAGE, EXIT_USAGE)
    words = args[i:]
    prompt = " ".join(words)
    if words == ["-"]:
        prompt = sys.stdin.read()
    if not prompt.strip():
        raise AkError("the prompt is empty. %s" % USAGE, EXIT_USAGE)
    if prompt.lstrip().startswith("-"):
        # Several CLIs take the prompt as a bare positional: a prompt that
        # looks like an option would be read as one (even an autonomy flag).
        raise AkError("a prompt cannot start with '-' (a CLI would read it as an option); "
                      "start it with a word", EXIT_USAGE)
    opts.prompt = prompt
    if opts.profile_token is None and env.get("AGENTKIT_PROFILE"):
        token = env["AGENTKIT_PROFILE"]
        opts.profile_token = token if token.startswith("@") else "@" + token
    return opts


# ------------------------------------------------------------ extraction

def _json_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _text_of_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def extract(extractor, stdout):
    """(result_text, reported_error) from a CLI's JSON output; falls back to
    the raw text when the shape is not recognised."""
    events = _json_lines(stdout)
    text = None
    error = False
    if extractor == "json-result":
        try:
            whole = json.loads(stdout)
            if isinstance(whole, dict):
                events = [whole]
        except ValueError:
            pass
        for ev in events:
            if "result" in ev and isinstance(ev["result"], str):
                text = ev["result"]
                error = bool(ev.get("is_error")) or ev.get("subtype", "success") not in ("success",)
    elif extractor == "codex-jsonl":
        for ev in events:
            item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
            if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text", "")
            if ev.get("type") in ("turn.failed", "error"):
                error = True
    elif extractor == "opencode-jsonl":
        for ev in events:
            part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
            if ev.get("type") == "text" and isinstance(part.get("text"), str):
                text = part["text"]
            if ev.get("type") == "error":
                error = True
    elif extractor == "pi-jsonl":
        for ev in events:
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            if msg.get("role") == "assistant":
                found = _text_of_content(msg.get("content"))
                if found:
                    text = found
                if msg.get("stopReason") == "error" or msg.get("errorMessage"):
                    error = True
    elif extractor == "cline-jsonl":
        last_say = None
        for ev in events:
            if ev.get("type") == "say" and isinstance(ev.get("text"), str):
                if ev.get("say") == "completion_result":
                    text = ev["text"]
                elif ev.get("say") == "error":
                    error = True
                last_say = ev["text"]
        if text is None:
            text = last_say
    if text is None:
        text = stdout.strip()
    return text, error


# -------------------------------------------------------------- running

def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + KILL_GRACE
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the group may outlive its leader
    except OSError:
        pass


def _pump(stream, sink, keep):
    """Copy the CLI's stdout to `sink` (our stdout or stderr) and keep the
    tail for extraction."""
    total = 0
    for chunk in iter(lambda: stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536), b""):
        sink.write(chunk)
        sink.flush()
        if keep is not None:
            keep.append(chunk)
            total += len(chunk)
            while total > CAPTURE_CAP and len(keep) > 1:
                total -= len(keep.popleft())
                keep.overflow = True


class _Tail(collections.deque):
    overflow = False


def execute(prep, argv, opts, cwd):
    """Run argv; returns (exit_code, cli_exit, stdout_text, overflow)."""
    # JSON: the CLI's stdout is captured for extraction and copied to stderr
    # (its transcript); text: the CLI writes to our stdout directly.
    capture = opts.fmt == "json"
    keep = _Tail() if capture else None
    popen_kw = {}
    if os.name == "nt":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kw["start_new_session"] = True
    sys.stdout.flush()
    sys.stderr.flush()
    argv = common.windows_argv(argv, prep.env)
    state = {"reason": None, "proc": None}

    def on_signal(signum, _frame):
        state["reason"] = "cancelled"
        if state["proc"] is not None:
            _kill_tree(state["proc"])

    # Handlers first: a SIGTERM that lands while the child is being created
    # must still cancel it, never leave it running unattended.
    old = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            old[sig] = signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass
    pump = None
    try:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=prep.env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else None, stderr=None, **popen_kw)
        except OSError as exc:
            raise AkError("%s failed to start: %s" % (argv[0], exc.strerror), EXIT_NOT_READY)
        state["proc"] = proc
        if state["reason"] == "cancelled":
            _kill_tree(proc)
        if capture:
            pump = threading.Thread(target=_pump, args=(proc.stdout, sys.stderr.buffer, keep))
            pump.daemon = True
            pump.start()
        deadline = time.time() + opts.timeout if opts.timeout else None
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if deadline is not None and time.time() >= deadline and state["reason"] is None:
                    state["reason"] = "timeout"
                    _kill_tree(proc)
        # The run is over: nothing it started may outlive it.
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    reason = state
    if pump is not None:
        pump.join(timeout=5)
    stdout_text = b"".join(keep).decode("utf-8", "replace") if keep is not None else ""
    cli_exit = proc.returncode
    if reason["reason"] == "timeout":
        return EXIT_TIMEOUT, cli_exit, stdout_text, bool(keep is not None and keep.overflow)
    if reason["reason"] == "cancelled":
        return EXIT_CANCELLED, cli_exit, stdout_text, bool(keep is not None and keep.overflow)
    code = EXIT_OK if cli_exit == 0 else EXIT_AGENT_FAILED
    return code, cli_exit, stdout_text, bool(keep is not None and keep.overflow)


def build_argv(prep, opts, cwd):
    cli = prep.kind.cli
    run = cli["run"]
    ctx = prep.ctx
    ctx.specials.update({"prompt": opts.prompt, "cwd": cwd,
                         "seconds": ("%d" % max(1, int(opts.timeout + 0.999))) if opts.timeout else ""})
    segments = {
        "provider": ctx.expand_list(prep.kind.data.get("args", [])),
        "json": list(run["json"]) if opts.fmt == "json" else [],
        "auto": list(cli["auto"]) if prep.auto else [],
        "timeout": ctx.expand_list(run.get("timeout", [])) if opts.timeout else [],
    }
    return [prep.exe] + ctx.expand_list(run["argv"], segments)


def envelope(opts, kind, profile, cwd, code, duration, result_text, cli_exit, truncated, error=None):
    out = {
        "interface": common.INTERFACE,
        "kind": kind,
        "profile": profile,
        "cwd": cwd,
        "exit": code,
        "duration_s": round(duration, 3),
        "result_text": result_text,
        "cli_exit": cli_exit,
        "truncated": truncated,
    }
    if error:
        out["error"] = error
    return out


def _early_format(args):
    """The requested format, known even when parsing fails later: a caller
    that asked for JSON gets a JSON envelope for every outcome."""
    for i, tok in enumerate(args):
        if tok == "--":
            break
        if tok == "--output-format" and i + 1 < len(args) and args[i + 1] == "json":
            return "json"
    return "text"


def main(model, args, env):
    start = time.time()
    fmt = _early_format(args)
    opts = None
    kind_name = args[0] if args and not args[0].startswith("-") else None
    profile_label = "@default"
    cwd = None
    try:
        opts = parse(args, env)
        fmt = opts.fmt
        if opts.kind not in model.kinds:
            raise AkError("unknown kind '%s'. Kinds: %s" % (opts.kind, " ".join(model.kind_names())), EXIT_USAGE)
        cwd = os.path.abspath(opts.cwd or os.getcwd())
        if not os.path.isdir(cwd):
            raise AkError("--cwd %s is not a directory" % cwd, EXIT_USAGE)
        head = launch.Head()
        head.profile_token = opts.profile_token
        head.auto = opts.auto
        head.ask = opts.ask
        prep = launch.prepare(model, opts.kind, head, env, purpose="run")
        profile_label = profiles.label(prep.profile)
        login = profiles.login_state(model, prep.kind.cli_name, prep.profile, prep.env) \
            if not prep.kind.key_var else True
        if login is False:
            command = prep.kind.cli.get("login", {}).get("command")
            if command and prep.profile:
                how = "ak profiles run %s %s -- %s" % (prep.kind.cli_name, profile_label, command)
            elif command:
                how = command
            else:
                how = "ak %s%s (it asks you to log in)" % (prep.kind.name, " " + profile_label if prep.profile else "")
            raise AkError("%s is not logged in for %s. Log in once with: %s"
                          % (prep.kind.cli["name"], profile_label, how), EXIT_NOT_READY)
        launch.finish_env(model, prep)
        argv = build_argv(prep, opts, cwd)
        if prep.kind.data.get("pre"):
            launch.run_pre(prep)
        code, cli_exit, stdout_text, overflow = execute(prep, argv, opts, cwd)
        result_text, reported_error = "", False
        if fmt == "json":
            result_text, reported_error = extract(prep.kind.cli["run"]["result"], stdout_text)
            if code == EXIT_OK and reported_error:
                code = EXIT_AGENT_FAILED
        truncated = overflow or len(result_text) > RESULT_CAP
        result_text = result_text[:RESULT_CAP]
        if fmt == "json":
            sys.stdout.write(json.dumps(envelope(opts, opts.kind, profile_label, cwd, code, time.time() - start,
                                                 result_text, cli_exit, truncated)) + "\n")
        return code
    except AkError as exc:
        if fmt != "json":
            raise
        common.warn(str(exc))
        sys.stdout.write(json.dumps(envelope(opts, kind_name, profile_label, cwd, exc.code, time.time() - start,
                                             "", None, False, error=str(exc))) + "\n")
        return exc.code
    except Exception as exc:  # pragma: no cover - a kit bug
        if fmt != "json":
            raise
        common.warn("internal error: %s: %s" % (exc.__class__.__name__, exc))
        sys.stdout.write(json.dumps(envelope(opts, kind_name, profile_label, cwd, EXIT_INTERNAL,
                                             time.time() - start, "", None, False,
                                             error="internal error")) + "\n")
        return EXIT_INTERNAL
