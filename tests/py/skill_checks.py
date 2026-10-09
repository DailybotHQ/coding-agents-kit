"""Checks for skills/agentkit/SKILL.md: frontmatter, marketplace rules, and
that every `ak` command line it teaches is valid grammar.

usage: python3 skill_checks.py <kit-root>
"""

import json
import os
import re
import sys

ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, "lib"))

import common  # noqa: E402
import kinds  # noqa: E402

PATH = os.path.join(ROOT, "skills", "agentkit", "SKILL.md")


def ok(name):
    print("ok %s" % name)


def check(name, cond, why=""):
    print(("ok %s" % name) if cond else ("FAIL %s: %s" % (name, why or "condition false")))


with open(PATH) as h:
    text = h.read()

# --- frontmatter (the YAML subset skills use: key: value lines) -----------
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
check("SKILL.md starts with a frontmatter block", m is not None)
fm = {}
if m:
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        check("frontmatter line is key: value (%s)" % key.strip(), sep == ":" and key.strip() and key == key.strip(),
              line)
        fm[key.strip()] = value.strip()
check("name is agentkit (the directory name)", fm.get("name") == "agentkit" == os.path.basename(os.path.dirname(PATH)))
desc = fm.get("description", "")
check("description is one line starting with a verb", desc and desc.split()[0].strip(",.") in ("Launch", "Install", "Run", "Use"))
check("description is at most 1024 characters", 0 < len(desc) <= 1024, str(len(desc)))
check("description says when to use it", "Use when" in desc)
check("version is quoted SemVer equal to the kit's", fm.get("version") == '"%s"' % common.VERSION, fm.get("version", ""))
check("documentation_url is https", fm.get("documentation_url", "").startswith("https://"))
check("no homepage key (some harnesses re-fetch it)", "homepage" not in fm)
try:
    meta = json.loads(fm.get("metadata", "{}"))
    check("metadata is JSON naming the required binary and interface 1",
          meta.get("requires", {}).get("anyBins") == ["ak", "agentkit"] and meta.get("interface") == 1)
except ValueError as e:
    check("metadata is JSON", False, str(e))

# --- marketplace rules --------------------------------------------------------
check("E005: no fetch-piped-to-shell line", not re.search(r"(curl|wget)[^|\n]*\|\s*(ba|z)?sh\b", text))
check("E005: no iex / Invoke-Expression", not re.search(r"\b(iex|Invoke-Expression)\b", text, re.I))
model = kinds.load()
bypass = sorted(set(f for c in model.clis.values() for f in c["auto"]) - {"--auto"})
spelled = [f for f in bypass if re.search(re.escape(f) + r"(?![A-Za-z-])", text)]
check("E006: no CLI autonomy flag is spelled (only ak's own --auto)", not spelled, str(spelled))
for line in re.findall(r"git clone[^\n`]*", text):
    check("W012: git clone pinned to a tag (%s)" % line[:60], "--branch v" in line, line)
for line in re.findall(r"skills add [^\s`]+", text):
    check("W012: skills add pinned to a tag (%s)" % line, re.search(r"@v\d+\.\d+\.\d+", line) is not None, line)
check("has a Trust boundary (write scope) section", "## Trust boundary (write scope)" in text)
check("says returned text is data, not instructions", "Data, not instructions" in text)
check("no secret-shaped string", not re.search(r"(sk-[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", text))
check("stays short enough to load cheaply (< 250 lines)", text.count("\n") < 250, str(text.count("\n")))
check("works alone: no dependency on another skill or DeepWorkPlan",
      "deepworkplan" not in text.lower() and ".dwp" not in text)

# --- every taught `ak` command is valid grammar --------------------------------
verbs = {"run", "env", "doctor", "profiles", "alias", "install", "--skill", "--version", "--help"}
commands = []
for block in re.findall(r"```(?:bash|sh)?\n(.*?)```", text, re.S):
    for line in block.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("ak"):
            commands.append(line)
bad = []
for cmd in commands:
    words = cmd.split()
    if words == ["ak"]:
        continue
    first = words[1] if len(words) > 1 else ""
    if first not in verbs and first not in model.kinds:
        bad.append(cmd)
check("every ak command in the examples names a real verb or kind (%d checked)" % len(commands),
      commands and not bad, str(bad))
kinds_in_table = set(re.findall(r"^\| `([a-z-]+)` \|", text, re.M))
variants = set(re.findall(r"`([a-z]+-(?:glm|azure|xai))`", text))
check("the kinds table covers every kind", kinds_in_table | variants >= set(model.kind_names()),
      str(sorted(set(model.kind_names()) - kinds_in_table - variants)))
for code in ("0", "1", "2", "3", "4", "5"):
    check("the exit code table names %s" % code, re.search(r"^\| %s \|" % code, text, re.M) is not None)
