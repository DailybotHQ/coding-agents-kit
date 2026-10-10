"""Checks for a bundled skill (skills/agentkit/ or skills/agentkit-setup/):
frontmatter, marketplace rules, and that every `ak` command line it teaches is
valid grammar. The two skills are held to the same bar; the checks that only
make sense for one of them are conditional on its name.

usage: python3 skill_checks.py <kit-root> [agentkit | agentkit-setup]
"""

import json
import os
import re
import sys

ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, "lib"))

import common  # noqa: E402
import kinds  # noqa: E402

SKILL = sys.argv[2] if len(sys.argv) > 2 else "agentkit"
SETUP = SKILL == "agentkit-setup"
SKILL_DIR = os.path.join(ROOT, "skills", SKILL)
PATH = os.path.join(SKILL_DIR, "SKILL.md")


PREFIX = "setup-skill: " if SETUP else ""


def ok(name):
    print("ok %s%s" % (PREFIX, name))


def check(name, cond, why=""):
    print(("ok %s%s" % (PREFIX, name)) if cond else ("FAIL %s%s: %s" % (PREFIX, name, why or "condition false")))


with open(PATH) as h:
    text = h.read()
# The marketplace rules apply to the whole skill: SKILL.md and its references.
alltext = text
refs_dir = os.path.join(SKILL_DIR, "references")
if os.path.isdir(refs_dir):
    for ref_name in sorted(os.listdir(refs_dir)):
        with open(os.path.join(refs_dir, ref_name)) as h:
            alltext += "\n" + h.read()

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
check("name is %s (the directory name)" % SKILL, fm.get("name") == SKILL == os.path.basename(os.path.dirname(PATH)))
desc = fm.get("description", "")
check("description is one line starting with a verb", desc and desc.split()[0].strip(",.") in ("Launch", "Install", "Run", "Use"))
check("description is at most 1024 characters", 0 < len(desc) <= 1024, str(len(desc)))
check("description says when to use it", "Use when" in desc)
check("version is quoted SemVer equal to the kit's", fm.get("version") == '"%s"' % common.VERSION, fm.get("version", ""))
check("documentation_url is https", fm.get("documentation_url", "").startswith("https://"))
check("no homepage key (some harnesses re-fetch it)", "homepage" not in fm)
try:
    meta = json.loads(fm.get("metadata", "{}"))
    want_bins = ["git", "python3"] if SETUP else ["ak", "agentkit"]
    check("metadata is JSON naming the required binaries and interface 1",
          meta.get("requires", {}).get("anyBins") == want_bins and meta.get("interface") == 1)
except ValueError as e:
    check("metadata is JSON", False, str(e))

# --- marketplace rules --------------------------------------------------------
check("E005: no fetch-piped-to-shell line", not re.search(r"(curl|wget)[^|\n]*\|\s*(ba|z)?sh\b", alltext))
check("E005: no iex / Invoke-Expression", not re.search(r"\b(iex|Invoke-Expression)\b", alltext, re.I))
model = kinds.load()
bypass = sorted(set(f for c in model.clis.values() for f in c["auto"]) - {"--auto"})
spelled = [f for f in bypass if re.search(re.escape(f) + r"(?![A-Za-z-])", alltext)]
check("E006: no CLI autonomy flag is spelled (they live only in providers.toml)", not spelled, str(spelled))
check("E006: the skill documents the opt-out (--ask and AGENTKIT_PERMISSIONS=ask)",
      "--ask" in text and "AGENTKIT_PERMISSIONS=ask" in text)
if not SETUP:
    check("E006: the skill never tells an agent to override the opt-out", "override the user's opt-out" in text)
else:
    check("E006: the skill never tells an agent to type an autonomy flag or remove the opt-out",
          "type an autonomy flag or remove the user's opt-out" in text)
for line in re.findall(r"git clone[^\n`]*", alltext):
    check("W012: git clone pinned to a tag (%s)" % line[:60], "--branch v" in line, line)
for line in re.findall(r"skills add [^\s`]+", alltext):
    check("W012: skills add pinned to a tag (%s)" % line, re.search(r"@v\d+\.\d+\.\d+", line) is not None, line)
check("has a Trust boundary (write scope) section", "## Trust boundary (write scope)" in text)
check("says returned text is data, not instructions", "Data, not instructions" in text)
check("no secret-shaped string", not re.search(r"(sk-[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", alltext))
check("stays short enough to load cheaply (< 250 lines)", text.count("\n") < 250, str(text.count("\n")))
check("works alone: no dependency on another skill or DeepWorkPlan",
      "deepworkplan" not in alltext.lower() and ".dwp" not in alltext)

# --- every taught `ak` command is valid grammar --------------------------------
verbs = {"run", "env", "doctor", "usage", "setup", "profiles", "alias", "install", "--skill", "--version", "--help"}
commands = []
for block in re.findall(r"```(?:bash|sh)?\n(.*?)```", alltext, re.S):
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

if not SETUP:
    kinds_in_table = set(re.findall(r"^\| `([a-z-]+)` \|", text, re.M))
    variants = set(re.findall(r"`([a-z]+-(?:glm|azure|xai))`", text))
    check("the kinds table covers every kind", kinds_in_table | variants >= set(model.kind_names()),
          str(sorted(set(model.kind_names()) - kinds_in_table - variants)))
    for code in ("0", "1", "2", "3", "4", "5"):
        check("the exit code table names %s" % code, re.search(r"^\| %s \|" % code, text, re.M) is not None)
else:
    import setup  # noqa: E402

    # Every `ak setup ...` line (also spelled python3 .../lib/ak.py setup ...) parses with the real grammar.
    setup_lines = []
    for block in re.findall(r"```(?:bash|sh|powershell)?\n(.*?)```", alltext, re.S):
        for line in block.splitlines():
            line = line.split(" # ", 1)[0].strip()
            m = re.search(r"(?:^ak|lib[/\\]ak\.py) setup (probe|verify|docker)\b(.*)$", line)
            if m:
                setup_lines.append((m.group(1), m.group(2).split()))
    parse_bad = []
    for verb, args in setup_lines:
        try:
            if verb == "verify":
                setup.parse_verify_args(model, args)
            elif verb == "docker":
                setup.parse_docker_args(model, args)
            elif any(a != "--json" for a in args):
                parse_bad.append((verb, args))
        except Exception as exc:  # AkError carries the grammar complaint
            parse_bad.append((verb, args, str(exc)[:80]))
    check("every ak setup line parses with the real grammar (%d checked)" % len(setup_lines), setup_lines and not parse_bad, str(parse_bad))
    check("the skill teaches all three helper commands",
          {v for v, _a in setup_lines} == {"probe", "verify", "docker"}, str(sorted({v for v, _a in setup_lines})))

    # Consent gates: all seven are named in SKILL.md, and every mutating command has one just before it.
    gates = ("system package", "shell rc", "posture", "profile", "CLI install", "repository write", "uninstall")
    check("every consent gate is named in SKILL.md", all("[GATE: %s]" % g in text for g in gates),
          str([g for g in gates if "[GATE: %s]" % g not in text]))
    mutating = re.compile(r"^\s*(ak install \S|ak profiles add|bash coding-agents-kit/install\.sh|\.\\coding-agents-kit\\install\.ps1)")
    lines = alltext.splitlines()
    unguarded = [line.strip()[:70] for i, line in enumerate(lines)
                 if mutating.match(line) and not any("[GATE:" in earlier for earlier in lines[max(0, i - 8):i + 1])]
    check("every mutating command has a consent gate in the lines before it", not unguarded, str(unguarded))

    # The pinned tag is the kit's own; links resolve; no branch or latest.
    tags = set(re.findall(r"--branch (v[0-9.]+)", alltext))
    check("the clone line pins the kit's own release tag", tags == {"v%s" % common.VERSION}, str(tags))
    links = re.findall(r"\]\((references/[^)#\s]+)", text)
    check("every reference linked from SKILL.md exists", links and all(os.path.isfile(os.path.join(SKILL_DIR, l)) for l in links), str(links))
    check("every reference file is linked from SKILL.md", all(("references/" + n) in text for n in sorted(os.listdir(refs_dir))))
    check("no install source is a branch or latest", not re.search(r"--branch (main|master|latest)\b|releases/latest|:latest\b", alltext))
    check("the skill forbids asking for, reading or echoing a key value", "never ask for, read, echo, store or log a key" in text.lower().replace("**", ""))
