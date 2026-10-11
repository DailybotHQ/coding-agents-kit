"""Checks for a bundled skill (skills/agentkit/, skills/agentkit-setup/ or
skills/agentkit-orchestrate/): frontmatter, marketplace rules, and that every
`ak` command line it teaches is valid grammar. The three skills are held to
the same bar; the checks that only make sense for one of them are conditional
on its name.

usage: python3 skill_checks.py <kit-root> [agentkit | agentkit-setup | agentkit-orchestrate]
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
ORCH = SKILL == "agentkit-orchestrate"
ENTRY = not SETUP and not ORCH
SKILL_DIR = os.path.join(ROOT, "skills", SKILL)
PATH = os.path.join(SKILL_DIR, "SKILL.md")


PREFIX = "setup-skill: " if SETUP else ("orchestrate-skill form: " if ORCH else "")


def ok(name):
    print("ok %s%s" % (PREFIX, name))


def check(name, cond, why=""):
    print(("ok %s%s" % (PREFIX, name)) if cond else ("FAIL %s%s: %s" % (PREFIX, name, why or "condition false")))


with open(PATH) as h:
    text = h.read()
# The marketplace rules apply to the whole skill: SKILL.md and its references.
alltext = text
refs_dir = os.path.join(SKILL_DIR, "references")
ref_texts = {}  # "references/<name>" -> text
if os.path.isdir(refs_dir):
    for ref_name in sorted(os.listdir(refs_dir)):
        with open(os.path.join(refs_dir, ref_name)) as h:
            ref_texts["references/" + ref_name] = h.read()
        alltext += "\n" + ref_texts["references/" + ref_name]

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
if ORCH:
    check("Herdr and Deep Work Plans stay optional (named only in a reference that says so)",
          "herdr pane" not in text and "(both optional)" in text and "Neither\nis required" in ref_texts.get("references/herdr-and-dwp.md", ""))

# --- every taught `ak` command is valid grammar --------------------------------
verbs = {"run", "env", "doctor", "usage", "pick", "setup", "profiles", "alias", "install", "--skill", "--version",
         "--help"}
commands = []
# A fence with any info string opens a block; only bash, sh and bare blocks hold commands (a closing fence of a
# ```text block must never be taken for an opening one).
for lang, block in re.findall(r"```([A-Za-z]*)\n(.*?)```", alltext, re.S):
    if lang not in ("", "bash", "sh"):
        continue
    for line in block.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("ak"):
            commands.append(line)
# Inline `ak …` spans in the references (tables, prose) follow the same rule; a placeholder (`ak <kind>`) is not
# a command.
for body in ref_texts.values():
    for span in re.findall(r"`(ak [^`\n]+)`", body):
        if not span.split()[1].startswith("<"):
            commands.append(span)
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

# --- every `ak pick` line parses with the real grammar ---------------------------
import pick  # noqa: E402

pick_bad = []
pick_lines = [c for c in commands if c.split()[:2] == ["ak", "pick"] and len(c.split()) > 2
              and not c.split()[2].startswith(("-", "<")) and "[" not in c]   # a mention or the grammar line is not a command
for cmd in pick_lines:
    try:
        pick.parse_args(cmd.split("#", 1)[0].split()[2:])
    except Exception as exc:  # AkError carries the grammar complaint
        pick_bad.append((cmd, str(exc)[:60]))
if pick_lines or ORCH:
    check("every ak pick line parses with the real grammar (%d checked)" % len(pick_lines), pick_lines and not pick_bad, str(pick_bad))

# --- every relative link in SKILL.md and the references resolves -------------
link_bad = []
for rel, body in [("SKILL.md", text)] + sorted(ref_texts.items()):
    base = os.path.dirname(os.path.join(SKILL_DIR, rel))
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", body):
        if re.match(r"[a-z]+:", target):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(base, target))):
            link_bad.append("%s -> %s" % (rel, target))
check("every relative link in SKILL.md and its references resolves", not link_bad, str(link_bad))

if ENTRY:
    for ref in ("references/accounts.md", "references/usage.md"):
        check("skill references: %s exists and is linked from SKILL.md" % ref,
              ref in ref_texts and "](%s)" % ref in text)
    usage_ref = ref_texts.get("references/usage.md", "")
    statuses = ("ok", "expired", "no_login", "no_scope", "rate_limited", "unsupported", "error")
    check("skill references: usage.md gives an action for every usage-v1 status",
          all(re.search(r"^\| `%s` \|" % st, usage_ref, re.M) for st in statuses),
          str([st for st in statuses if not re.search(r"^\| `%s` \|" % st, usage_ref, re.M)]))
    pick_exits = re.findall(r"^\| (0|1|2|3|≥ 64) \|", usage_ref.split("## Choosing an account", 1)[-1], re.M)
    check("skill references: usage.md names the ak pick exit codes 0, 1, 2, 3 and >= 64",
          pick_exits[:5] == ["0", "1", "2", "3", "≥ 64"], str(pick_exits))
    check("skill references: usage.md carries the worked examples E1-E8",
          all("| E%d | `ak pick " % i in usage_ref for i in range(1, 9)))
    check("skill references: SKILL.md puts ak pick in the trust boundary",
          "`ak pick`" in text.split("## Trust boundary (write scope)", 1)[-1])

if ENTRY:
    kinds_in_table = set(re.findall(r"^\| `([a-z-]+)` \|", text, re.M))
    variants = set(re.findall(r"`([a-z]+-(?:glm|azure|xai))`", text))
    check("the kinds table covers every kind", kinds_in_table | variants >= set(model.kind_names()),
          str(sorted(set(model.kind_names()) - kinds_in_table - variants)))
    for code in ("0", "1", "2", "3", "4", "5"):
        check("the exit code table names %s" % code, re.search(r"^\| %s \|" % code, text, re.M) is not None)
elif SETUP:
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

if ORCH:
    unattended = ref_texts.get("references/unattended.md", "")
    check("the unattended reference names the standing grant and escalates logins, permission requests, destructive and unknown screens",
          "standing grant" in unattended and all(w in unattended for w in ("login", "per-action permission", "destructive", "cannot name")))
    check("no agent answers the bypass-permissions acknowledgement (named plainly; escalated)",
          "**No agent ever answers it.**" in unattended and "bypass-permissions acknowledgement" in unattended.split("## 4.", 1)[-1]
          and "accept" not in unattended.split("## 3.", 1)[-1].split("## 4.", 1)[0].lower().replace("accept the risk", ""))
    check("the only keystroke is folder trust, on a pane the lead launched, when --trust-cwd was unavailable",
          "only when `--trust-cwd` could not be used" in unattended and "a pane the lead launched itself" in unattended)
    for ref in ("references/patterns.md", "references/herdr-and-dwp.md", "references/unattended.md"):
        check("%s exists and is linked from SKILL.md" % ref, ref in ref_texts and "](%s)" % ref in text)
    import run as runmod  # noqa: E402
    run_lines = [c for c in commands if c.split()[:2] == ["ak", "run"] and len(c.split()) > 2]
    run_bad = [c for c in run_lines if " -- " not in c or "--cwd" not in c and "PLAN.md" not in c and "Review" not in c]
    check("every ak run line separates the prompt with -- (%d checked)" % len(run_lines), run_lines and not [c for c in run_lines if " -- " not in c], str(run_bad))
    writers = [c for c in run_lines if "commit" in c.lower()]
    check("every writing delegate runs in its own worktree (--cwd ../wt-*)", writers and all(re.search(r"--cwd \.\./wt-[a-z0-9-]+", c) for c in writers), str(writers))
    check("the loop says once per batch, never in a loop", "never in a loop" in text and not re.search(r"(while|watch)\s[^\n]*ak (usage|pick)", alltext))
    check("the skill forbids putting a secret in a prompt", "put a key, token or secret in a prompt" in text)
    check("the skill forbids getting around a limit the user is not entitled to exceed", "not entitled to exceed" in text)
    check("one writer per path is a rule", "one writer per path" in text.lower())
    check("every fenced example the scenarios run is marked (# test: inventory, fanout, pick, review)",
          all("# test: %s" % t in text for t in ("inventory", "fanout", "pick", "review")))
