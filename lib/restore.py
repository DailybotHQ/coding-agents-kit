"""Resume through ak after a Herdr restart.

Herdr restores an agent pane from the session reference the CLI's Herdr
integration reports (`pane.report_agent_session`). Without more, it restarts
the bare CLI (`claude --resume <id>`): no profile home, no key from the env
file, no autonomy flag — the wrong account, or a login screen. A report may
also carry `resume_argv`, the command Herdr runs instead.

An interactive `ak <kind> [@profile]` inside a Herdr pane (HERDR_ENV=1 and
HERDR_PANE_ID set) starts one detached watcher next to the CLI. The watcher
reads the pane through the `herdr` CLI and, whenever Herdr records a new
session id for that CLI, reports it again with

    resume_argv = ak <kind> @<profile> [--ask] --resume <id>

under the same source and agent, with a later seq. It reports again on every
id change because Herdr keeps an earlier resume_argv when a later report
omits it, which would resume the previous conversation after a /clear. The
watcher exits with the CLI (the launch's pid: ak replaces itself with the CLI
on macOS and Linux and stays its parent on Windows).

It needs the CLI's Herdr integration in that home (`ak profiles hooks <cli>
@name` for a profile); without a reported id there is nothing to resume.
AGENTKIT_HERDR_RESUME=0 turns it off. The watcher gets no secret: its
environment is PATH, the home and temp variables and Herdr's own HERDR_*.
"""

import json
import os
import subprocess
import sys
import time

import common

ENV_SWITCH = "AGENTKIT_HERDR_RESUME"
ENV_INTERVAL = "AGENTKIT_HERDR_RESUME_INTERVAL"   # seconds between reads (tests)
DEFAULT_INTERVAL = 2.0
MAX_FAILURES = 30          # consecutive unreadable panes before giving up
CALL_TIMEOUT = 10

# What the watcher keeps of the launch's environment: never a key.
_KEEP = ("PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE",
         "WINDIR", "COMSPEC", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
         "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", ENV_INTERVAL)


def argv_prefix(kind_name, profile_name, auto):
    """The resume command without its id: ak <kind> @<profile> [--ask] --resume.

    The profile is always explicit, @default included: a default profile or
    AGENTKIT_PROFILE at restore time must not move the session to another
    account. --ask keeps an opted-out launch opted out."""
    argv = ["ak", kind_name, "@%s" % (profile_name or "default")]
    if not auto:
        argv.append("--ask")
    return argv + ["--resume"]


def valid_argv(argv):
    """Herdr's rules for resume_argv: a plain command name first, no
    apostrophe and no control character anywhere."""
    if not argv or os.sep in argv[0] or "/" in argv[0]:
        return False
    for arg in argv:
        if not arg or "'" in arg or any(ord(ch) < 32 or ord(ch) == 127 for ch in arg):
            return False
    return True


def wanted(prep, env):
    """True when this launch should keep Herdr's resume command on ak."""
    if (env.get(ENV_SWITCH) or "1").strip() == "0":
        return False
    if env.get("HERDR_ENV") != "1" or not env.get("HERDR_PANE_ID"):
        return False
    cli = prep.kind.cli
    return bool(cli.get("herdr_kind")) and "resume" in cli.get("session", {})


def watcher_env(env):
    return dict((k, v) for k, v in env.items() if k in _KEEP or k.startswith("HERDR_"))


def start(prep, env):
    """Start the watcher for this launch; never fails the launch."""
    if not wanted(prep, env):
        return None
    herdr = common.which("herdr", env)
    if not herdr:
        return None
    spec = {
        "herdr": herdr,
        "pane": env["HERDR_PANE_ID"],
        "agent": prep.kind.cli["herdr_kind"],
        "pid": os.getpid(),
        "prefix": argv_prefix(prep.kind.name, prep.profile, prep.auto),
    }
    argv = [sys.executable, os.path.abspath(__file__), "watch", json.dumps(spec)]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "env": watcher_env(env), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x8000000))
    else:
        kwargs["start_new_session"] = True
    try:
        child = subprocess.Popen(argv, **kwargs)
    except OSError:
        return None
    if os.name != "nt":
        # The watcher forks and its first process exits at once: waiting here
        # leaves no zombie under the CLI, which takes over this pid.
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    return child


# ------------------------------------------------------------------ watcher

def alive(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def herdr_call(herdr, args):
    """Run `herdr <args>`; (exit status, stdout text)."""
    try:
        done = subprocess.run([herdr] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=CALL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout.decode("utf-8", "replace")


def pane_session(text):
    """The pane's agent_session from `herdr pane get` output, or None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    pane = (data.get("result") or {}).get("pane") if isinstance(data, dict) else None
    session = pane.get("agent_session") if isinstance(pane, dict) else None
    return session if isinstance(session, dict) else None


def report_args(spec, session):
    """The `herdr pane report-agent-session` arguments for a session, or None
    when it is not this CLI's id or the command would break Herdr's rules."""
    if session.get("agent") != spec["agent"] or session.get("kind") != "id":
        return None
    sid, source = session.get("value"), session.get("source")
    if not isinstance(sid, str) or not sid or not isinstance(source, str) or not source:
        return None
    argv = list(spec["prefix"]) + [sid]
    if not valid_argv(argv):
        return None
    return ["pane", "report-agent-session", spec["pane"], "--source", source, "--agent", spec["agent"],
            "--seq", str(time.time_ns()), "--agent-session-id", sid, "--"] + argv


def watch(spec, call=herdr_call, is_alive=alive, sleep=time.sleep, interval=None):
    """Keep the pane's resume command on ak until the CLI exits. Returns the
    session ids it reported (in order)."""
    if interval is None:
        try:
            interval = float(os.environ.get(ENV_INTERVAL) or DEFAULT_INTERVAL)
        except ValueError:
            interval = DEFAULT_INTERVAL
    reported = []
    last = None
    failures = 0
    while is_alive(spec["pid"]):
        status, text = call(spec["herdr"], ["pane", "get", spec["pane"]])
        if status != 0:
            failures += 1
            if failures >= MAX_FAILURES:
                break
        else:
            failures = 0
            session = pane_session(text)
            if session and session.get("value") != last:
                args = report_args(spec, session)
                if args is None:
                    last = session.get("value")
                elif call(spec["herdr"], args)[0] == 0:
                    last = session["value"]
                    reported.append(last)
        sleep(interval)
    return reported


def _detach():
    """POSIX: fork once more so the watcher is nobody's zombie."""
    if os.name == "nt":
        return
    if os.fork() > 0:
        os._exit(0)


def main(argv):
    if len(argv) != 2 or argv[0] != "watch":
        sys.stderr.write("usage: restore.py watch <spec>\n")
        return 2
    try:
        spec = json.loads(argv[1])
    except ValueError:
        return 2
    _detach()
    try:
        watch(spec)
    except Exception:  # a watcher never surfaces an error into the pane
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
