"""Regressions for the pre-release review findings that are best checked at
unit level (env-file parser, TOML escaping, Windows argv safety).

usage: python3 review_checks.py <kit-root> <scratch-dir>
"""

import os
import sys

ROOT, SCRATCH = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, "lib"))

import common  # noqa: E402
import writers  # noqa: E402


def check(name, cond, why=""):
    print(("ok %s" % name) if cond else ("FAIL %s: %s" % (name, why or "condition false")))


# Env-file parser: a comment after a quoted value is not part of it.
envf = os.path.join(SCRATCH, "env")
with open(envf, "w") as h:
    h.write('A="abc"  # note\nB=\'x y\' # c\nC=plain # c\nexport D="q#q"\nE="unterminated\n')
env = {"AGENTKIT_ENV": envf, "HOME": SCRATCH}
common.load_env_file(env)
check("env parser: quoted value with a trailing comment", env.get("A") == "abc", repr(env.get("A")))
check("env parser: single quotes keep spaces", env.get("B") == "x y", repr(env.get("B")))
check("env parser: unquoted value drops the comment", env.get("C") == "plain", repr(env.get("C")))
check("env parser: # inside quotes is kept", env.get("D") == "q#q", repr(env.get("D")))

# TOML: a value can never start a new line in a Codex overlay.
cx = os.path.join(SCRATCH, "x.config.toml")
writers.write_codex(cx, "ZAI", "n", "https://u", "ZAI_CODING_API_KEY", 'glm\nsandbox_mode = "danger-full-access"')
with open(cx) as h:
    lines = h.read().splitlines()
check("codex overlay: a newline in a value cannot inject a key",
      not any(l.startswith("sandbox_mode") for l in lines) and len(lines) == 8, repr(lines))
try:
    import tomllib
    with open(cx, "rb") as h:
        check("codex overlay stays valid TOML with the value intact",
              tomllib.load(h)["model"] == 'glm\nsandbox_mode = "danger-full-access"')
except ImportError:
    check("codex overlay escaping (no tomllib to parse back on this python)", True)

# Windows argv safety, exercised with os.name patched.
shim_dir = os.path.join(SCRATCH, "npm")
os.makedirs(os.path.join(shim_dir, "node_modules", "@openai", "codex", "bin"))
script = os.path.join(shim_dir, "node_modules", "@openai", "codex", "bin", "codex.js")
open(script, "w").close()
with open(os.path.join(shim_dir, "codex.cmd"), "w") as h:
    h.write('@ECHO off\r\nSET dp0=%~dp0\r\n"%_prog%"  "%dp0%\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n')
with open(os.path.join(shim_dir, "other.cmd"), "w") as h:
    h.write("@echo off\r\nsomething %*\r\n")
node = os.path.join(SCRATCH, "node.exe")
open(node, "w").close()
os.chmod(node, 0o755)
real_name = os.name
try:
    common.os.name = "nt"
    os.environ["PATHEXT"] = ".EXE"
    argv = common.windows_argv([os.path.join(shim_dir, "codex.cmd"), 'x" & calc & "'], {"PATH": SCRATCH})
    check("windows: an npm .cmd shim is started as node <script> (no cmd.exe re-parse)",
          argv[1:] == [script, 'x" & calc & "'] and argv[0].endswith("node.exe"), repr(argv))
    try:
        common.windows_argv([os.path.join(shim_dir, "other.cmd"), 'x" & calc'], {"PATH": SCRATCH})
        check("windows: cmd metacharacters to another batch file are refused", False, "accepted")
    except common.AkError:
        check("windows: cmd metacharacters to another batch file are refused", True)
    check("windows: a plain argument to a batch file is allowed",
          common.windows_argv([os.path.join(shim_dir, "other.cmd"), "hello world"], {"PATH": SCRATCH})[1] == "hello world")
finally:
    common.os.name = real_name
