"""Shared helpers of the python core: errors, exit codes, paths, lookups."""

import os
import platform
import subprocess
import sys

VERSION = "0.1.0"
INTERFACE = 1

# Exit codes (the `ak run` contract uses the same numbers everywhere).
EXIT_OK = 0
EXIT_AGENT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_READY = 3      # CLI not installed, not logged in, key or profile missing
EXIT_TIMEOUT = 4
EXIT_CANCELLED = 5
EXIT_INTERNAL = 70      # >= 64: kit internal error

KIT_ROOT = os.environ.get("AGENTKIT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AkError(Exception):
    """An error the user can act on. The message names variables and
    commands, never a secret value."""

    def __init__(self, message, code=EXIT_USAGE):
        Exception.__init__(self, message)
        self.code = code


def warn(message):
    sys.stderr.write("ak: %s\n" % message)


def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def env_file():
    return os.environ.get("AGENTKIT_ENV") or os.path.join(home(), ".config", "agentkit", "env")


def data_dir():
    """Install + profiles root (contract: ~/.local/share/agentkit)."""
    return os.environ.get("AGENTKIT_HOME") or os.path.join(home(), ".local", "share", "agentkit")


def os_name():
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    if system == "Windows" or system.startswith(("MINGW", "MSYS", "CYGWIN")):
        return "windows"
    return "unknown"


def which(name, env=None):
    path = (env or os.environ).get("PATH", "")
    exts = [""]
    if os.name == "nt":
        # PATHEXT only: npm writes an extensionless sh script next to each
        # .cmd shim, and Windows cannot start it (WinError 193).
        exts = [e for e in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").lower().split(";") if e]
    for directory in path.split(os.pathsep):
        if not directory:
            continue
        for ext in exts:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _probe(argv, timeout=5):
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, timeout=timeout)
        return out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def is_cursor_binary(path):
    """The Cursor CLI ships `agent`, and so does the xAI Grok installer:
    a bare `agent` on PATH is not proof that Cursor is installed."""
    resolved = os.path.realpath(path)
    lowered = resolved.lower()
    if "/.grok/" in lowered or any(t in lowered for t in ("grok-macos", "grok-linux", "grok-windows")):
        return False
    if "cursor-agent" in lowered:
        return True
    if _probe([path, "--version"]).lower().startswith("grok"):
        return False
    if os.path.basename(path) == "cursor-agent":
        return True
    return "cursor" in _probe([path, "--help"]).lower()


def resolve_executable(cli, env=None):
    """Absolute path of a CLI's executable, or None when not installed."""
    if cli.get("resolver") != "cursor":
        return which(cli["executable"], env)
    for candidate in ("cursor-agent", cli["executable"]):
        path = which(candidate, env)
        if path and is_cursor_binary(path):
            return path
    versions = os.path.join(home(), ".local", "share", "cursor-agent", "versions")
    best = None
    if os.path.isdir(versions):
        for entry in os.listdir(versions):
            path = os.path.join(versions, entry, "cursor-agent")
            if os.access(path, os.X_OK) and (best is None or os.path.getmtime(path) > os.path.getmtime(best)):
                best = path
    return best


_CMD_META = set('"%&|<>^!')


def windows_argv(argv, env=None):
    """On Windows, a .cmd/.bat target is re-parsed by cmd.exe, so an argument
    with a quote and & | < > can run commands (the "BatBadBut" class).
    npm's shims are resolved to `node <script>`; any other batch target gets
    no argument containing a cmd metacharacter."""
    if os.name != "nt" or not argv[0].lower().endswith((".cmd", ".bat")):
        return argv
    script = _npm_shim_target(argv[0])
    node = which("node", env)
    if script and node:
        return [node, script] + list(argv[1:])
    if any(_CMD_META & set(a) for a in argv[1:]):
        raise AkError("%s is a batch file and an argument contains one of %s, which cmd.exe would interpret; "
                      "refusing to start it" % (argv[0], "".join(sorted(_CMD_META))), EXIT_USAGE)
    return argv


def _npm_shim_target(path):
    """The JavaScript file an npm .cmd shim runs, or None."""
    import re
    try:
        with open(path, errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    # cmd-shim writes "%dp0%\node_modules\…\cli.js" (older: "%~dp0\…").
    match = re.search(r'"%(?:dp0%|~dp0)\\([^"%]+\.(?:js|cjs|mjs))"', text)
    if not match:
        return None
    target = os.path.join(os.path.dirname(path), *match.group(1).split("\\"))
    return target if os.path.isfile(target) else None


def secret_like(name):
    return name.endswith("_API_KEY") or "_API_KEY_" in name or name.endswith("_TOKEN") or "_TOKEN_" in name


def load_env_file(env):
    """Read the env file into `env` when no shell did (Windows, or the core
    started directly). The shell launcher sources the file instead, which
    also allows shell code in it; here only the KEY=VALUE subset is read:
    `KEY=value`, `export KEY=value`, values in '...' or "...", # comments.
    Nothing is expanded or executed."""
    if env.get("AGENTKIT_ENV_LOADED") == "1":
        return
    path = env.get("AGENTKIT_ENV") or os.path.join(env.get("HOME") or home(), ".config", "agentkit", "env")
    try:
        with open(path) as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]   # quoted: up to the closing quote
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()    # unquoted: drop a trailing comment
        env[name] = value
