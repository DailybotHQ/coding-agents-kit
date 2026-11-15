"""`ak last [-r] | ak last ls`: back to the last session in this directory.

Every interactive `ak <kind> [@profile]` records, per working directory,
which kind and profile it launched (and whether it opted out of autonomy).
`ak last` launches that again with `-c`, so the CLI continues its newest
session there, in the same account, in any terminal — Herdr or not. `-r`
opens the CLI's session picker instead. `ak last ls` shows what is recorded.

The record lives in the kit's state directory (`launches.json`, 0600,
lib/state.py): a directory path, a kind, a profile name, a flag and a time,
never a key, a session id or anything the CLI wrote. It keeps the most
recent MAX_DIRS directories. Recording is best effort: a failure never stops
a launch.
"""

import os
import time

import common
import state
from common import AkError, EXIT_USAGE

SCHEMA = "launches-v1"
MAX_DIRS = 200


def _path(env):
    return os.path.join(state.root(env), "launches.json")


def _here():
    return os.path.realpath(os.getcwd())


def _load(env):
    doc = state.read_json(_path(env))
    if not doc or doc.get("schema") != SCHEMA or not isinstance(doc.get("dirs"), dict):
        return {}
    return dict((d, e) for d, e in doc["dirs"].items() if _valid(e))


def _valid(entry):
    return (isinstance(entry, dict) and isinstance(entry.get("kind"), str) and isinstance(entry.get("profile"), str)
            and isinstance(entry.get("at"), int) and not isinstance(entry.get("at"), bool))


def record(env, kind_name, profile_name, auto, directory=None, now=None):
    """Remember this launch for its directory. Returns True when written."""
    try:
        dirs = _load(env)
        dirs[directory or _here()] = {"kind": kind_name, "profile": profile_name or "default", "ask": not auto,
                                      "at": int(now if now is not None else time.time())}
        if len(dirs) > MAX_DIRS:
            keep = sorted(dirs, key=lambda d: dirs[d]["at"], reverse=True)[:MAX_DIRS]
            dirs = dict((d, dirs[d]) for d in keep)
        state.write_json(_path(env), {"schema": SCHEMA, "dirs": dirs})
    except (OSError, ValueError):
        return False
    return True


def command(entry, session_flag="-c"):
    """The ak arguments that go back to a recorded launch."""
    args = [entry["kind"], "@" + entry["profile"]]
    if entry.get("ask"):
        args.append("--ask")
    return args + [session_flag]


def main(model, args, env):
    if args in (["ls"], ["list"]):
        dirs = _load(env)
        if not dirs:
            print("no ak launch recorded yet")
            return 0
        for d in sorted(dirs, key=lambda x: dirs[x]["at"], reverse=True):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(dirs[d]["at"]))
            print("%s  ak %s  %s" % (stamp, " ".join(command(dirs[d])[:-1]), d))
        return 0
    if args not in ([], ["-c"], ["--continue"], ["-r"], ["--resume"]):
        raise AkError("usage: ak last [-c | -r] | ak last ls", EXIT_USAGE)
    here = _here()
    entry = _load(env).get(here)
    if not entry:
        raise AkError("no ak launch recorded in %s. Start one with ak <kind> [@profile]; "
                      "ak last ls shows the directories with one" % here, EXIT_USAGE)
    if model.canonical(entry["kind"]) not in model.kinds:
        raise AkError("the recorded kind '%s' is not known to this version of ak" % entry["kind"], EXIT_USAGE)
    argv = command(entry, "-r" if args and args[0] in ("-r", "--resume") else "-c")
    common.warn("ak %s" % " ".join(argv))
    import launch
    return launch.launch(model, model.canonical(argv[0]), argv[1:], env)
