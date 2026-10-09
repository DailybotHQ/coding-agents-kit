"""Checks for the kinds model (lib/kinds.py, lib/tomlmini.py, lib/writers.py).

Run by tests/scopes/kinds.sh: python3 kinds_checks.py <kit-root> <scratch-dir>
Prints one `ok <name>` / `FAIL <name>: <why>` line per check.
"""

import json
import os
import stat
import sys

ROOT, SCRATCH = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, "lib"))

import kinds  # noqa: E402
import tomlmini  # noqa: E402
import writers  # noqa: E402

PLANTED = "planted-secret-value-7f3a9c"


def ok(name):
    print("ok %s" % name)


def bad(name, why):
    print("FAIL %s: %s" % (name, why))


def check(name, cond, why=""):
    if cond:
        ok(name)
    else:
        bad(name, why or "condition false")


def raises(fn, exc=Exception):
    try:
        fn()
    except exc as e:
        return str(e) or e.__class__.__name__
    return None


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


model = kinds.load()
ok("providers.toml loads and validates")

# --- the contract's kinds table (ECOSYSTEM_CONTRACT §2.1) ----------------
CONTRACT = {
    "claude": ("claude", "CLAUDE_CONFIG_DIR", ["claude-glm"]),
    "codex": ("codex", "CODEX_HOME", ["codex-glm", "codex-azure", "codex-xai"]),
    "cursor": ("agent", None, []),
    "opencode": ("opencode", None, ["opencode-glm", "opencode-azure", "opencode-xai"]),
    "pi": ("pi", "PI_CODING_AGENT_DIR", ["pi-glm", "pi-azure", "pi-xai"]),
    "cline": ("cline", "CLINE_DIR", ["cline-azure", "cline-xai"]),
    "grok": ("grok", "GROK_HOME", []),
}
expected_kinds = set()
for cli, (exe, home_env, variants) in CONTRACT.items():
    for name in [cli] + variants:
        expected_kinds.add(name)
        try:
            k = model.kind(name)
        except kinds.KindsError as e:
            bad("kind %s resolves" % name, str(e))
            continue
        check("kind %s runs %s" % (name, exe), k.executable == exe and k.cli_name == cli,
              "%s/%s" % (k.executable, k.cli_name))
    c = model.clis[cli]
    check("cli %s herdr kind is %s" % (cli, cli), c.get("herdr_kind") == cli, str(c.get("herdr_kind")))
    if home_env:
        check("cli %s isolates profiles with %s" % (cli, home_env), c.get("home_env") == home_env,
              str(c.get("home_env")))
check("cursor isolates with its own HOME", model.clis["cursor"]["isolation"] == "cursor-home")
check("opencode isolates with the XDG directories", model.clis["opencode"]["isolation"] == "xdg")
check("the model has exactly the contract's kinds", set(model.kind_names()) == expected_kinds,
      str(sorted(set(model.kind_names()) ^ expected_kinds)))

PROVIDER_KEYS = {"glm": "ZAI_CODING_API_KEY", "azure": "AZURE_OPENAI_API_KEY", "xai": "XAI_API_KEY"}
for name in model.kind_names():
    suffix = name.split("-", 1)[1] if "-" in name else None
    if suffix:
        check("kind %s reads %s" % (name, PROVIDER_KEYS[suffix]), model.kind(name).key_var == PROVIDER_KEYS[suffix])
check("grok's key is optional (its own login otherwise)", model.kind("grok").key_optional)

# --- parsers agree --------------------------------------------------------
with open(kinds.PROVIDERS_FILE, "rb") as h:
    mini = tomlmini.load(h)
try:
    import tomllib
    with open(kinds.PROVIDERS_FILE, "rb") as h:
        check("tomlmini reads providers.toml exactly as tomllib", tomllib.load(h) == mini)
except ImportError:
    ok("tomlmini reads providers.toml (no tomllib on this python: fallback in use)")
check("tomlmini refuses arrays of tables with a line number",
      "line 2" in (raises(lambda: tomlmini.loads("a = 1\n[[x]]\n"), tomlmini.TOMLError) or ""))
check("tomlmini refuses duplicate keys", raises(lambda: tomlmini.loads("a = 1\na = 2\n"), tomlmini.TOMLError))
check("tomlmini reads escapes, inline tables and multi-line arrays",
      tomlmini.loads('a = "x\\"\\u00e9"\nb = { c = [1,\n 2, ], d = \'lit\' }\n') ==
      {"a": 'x"\u00e9', "b": {"c": [1, 2], "d": "lit"}})

# --- validation rejects bad data -----------------------------------------
with open(kinds.PROVIDERS_FILE) as h:
    base_text = h.read()


def variant(name, text):
    path = os.path.join(SCRATCH, name + ".toml")
    with open(path, "w") as h:
        h.write(text)
    return path


cases = {
    "an unknown cli": base_text + '\n[kinds.nope]\ncli = "nope"\n',
    "an unknown provider": base_text.replace('[kinds.codex-glm]\ncli = "codex"\nprovider = "zai"',
                                             '[kinds.codex-glm]\ncli = "codex"\nprovider = "nope"'),
    "a key on argv for a non-cline CLI": base_text.replace('args = ["-p", "glm"]', 'args = ["-p", "glm", "{key}"]'),
    "a key in a writer": base_text.replace('base_url = "{codex_base}"', 'base_url = "{key}"'),
    "an install without a version": base_text.replace('version = "0.158.0"', 'version = ""'),
    "the retired unpinned key": base_text.replace('version = "0.158.0"', 'version = "0.158.0"\nunpinned = "x"'),
    "an npm install without integrity": base_text.replace('integrity = "sha512-GBhc', 'integrity_x = "sha512-GBhc'),
    "a short sha256": base_text.replace('linux-x64 = "4503bfe11a6c7fcc1e0b39b5e0d347c04248f750b03b0977b3ad6b531fe6f358"',
                                        'linux-x64 = "4503bfe1"'),
    "a platform without a digest": base_text.replace('linux-x64 = "4503bfe11a6c7fcc1e0b39b5e0d347c04248f750b03b0977b3ad6b531fe6f358", ', ''),
    "an unknown platform": base_text.replace('linux-x64 = "linux-x64", linux-arm64', 'beos-x64 = "linux-x64", linux-arm64'),
    "a url without {platform}": base_text.replace('/{platform}/claude', '/linux-x64/claude'),
    "the retired script channel": base_text.replace('channel = "binary"\nversion = "2.1.295"', 'channel = "script"\nversion = "2.1.295"'),
    "a wrong schema": base_text.replace("schema = 1", "schema = 2"),
    "a key in the autonomy flag": base_text.replace('auto = ["--approve"]', 'auto = ["--approve", "{key}"]'),
    "an http artifact": base_text.replace("https://downloads.claude.ai/", "http://downloads.claude.ai/"),
}
for label, text in cases.items():
    if text == base_text:
        check("the %s case changes the data" % label, False, "replacement did not apply")
        continue
    err = raises(lambda: kinds.load(variant("bad", text)), kinds.KindsError)
    check("validation refuses %s" % label, err is not None, "accepted")
model_now = kinds.load()
for cli_name in model_now.cli_names():
    inst = model_now.clis[cli_name]["install"]
    check("%s is pinned and verified (%s, no unverified exception)" % (cli_name, inst["channel"]),
          not kinds.install_problems(inst) and not inst.get("unverified")
          and (inst["channel"] == "npm" or {"linux-x64", "linux-arm64", "macos-x64", "macos-arm64"} <= set(inst["sha256"])),
          str(kinds.install_problems(inst)))
added = base_text + '\n[kinds.claude-xai]\ncli = "claude"\nprovider = "xai"\n[kinds.claude-xai.env]\nANTHROPIC_AUTH_TOKEN = "{key}"\nANTHROPIC_BASE_URL = "{base}"\n'
try:
    m2 = kinds.load(variant("added", added))
    k2 = m2.kind("claude-xai")
    ctx = kinds.Context(k2, {"XAI_API_KEY": PLANTED}, SCRATCH)
    env, skipped = kinds.provider_env(k2, ctx, include_secret=False)
    check("a new kind is one data entry (claude-xai resolves)",
          k2.executable == "claude" and env == {"ANTHROPIC_BASE_URL": "https://api.x.ai/v1"} and skipped == ["ANTHROPIC_AUTH_TOKEN"],
          "%r %r" % (env, skipped))
except kinds.KindsError as e:
    bad("a new kind is one data entry (claude-xai resolves)", str(e))
check("an unknown kind names the valid ones",
      "claude-glm" in (raises(lambda: model.kind("claudee"), kinds.KindsError) or ""))

# --- templates --------------------------------------------------------------
look = {"A": "a", "EMPTY": "", "v": "vee"}.get
check("template reads env and variables", kinds.expand("{A}-{v}", look) == "a-vee")
check("template default when unset", kinds.expand("{NOPE:-d}", look) == "d")
check("template default when empty", kinds.expand("{EMPTY:-d}", look) == "d")
check("template defaults nest", kinds.expand("{NOPE:-{EMPTY:-{A}}}x", look) == "ax")
check("template refuses an unclosed brace", raises(lambda: kinds.expand("{A", look), kinds.KindsError))
check("references_secret sees {key} inside a default", kinds.references_secret("{X:-{key}}"))

# --- secrets in resolution ----------------------------------------------------
glm = model.kind("claude-glm")
env_in = {"ZAI_CODING_API_KEY": PLANTED}
ctx = kinds.Context(glm, env_in, SCRATCH)
check("a printing context cannot read {key}",
      raises(lambda: ctx.expand("{key}"), kinds.SecretReference) is not None)
printed, skipped = kinds.provider_env(glm, ctx, include_secret=False)
check("printable env of claude-glm has no secret", PLANTED not in json.dumps(printed) and
      skipped == ["ANTHROPIC_AUTH_TOKEN"], json.dumps(skipped))
check("claude-glm defaults (Z.AI base URL, models)",
      printed.get("ANTHROPIC_BASE_URL") == "https://api.z.ai/api/anthropic" and
      printed.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "glm-5.3-flash" and
      "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in printed, json.dumps(printed))
lctx = kinds.Context(glm, env_in, SCRATCH, allow_secret=True)
launch, _ = kinds.provider_env(glm, lctx, include_secret=True)
check("the launch env of claude-glm carries the key", launch.get("ANTHROPIC_AUTH_TOKEN") == PLANTED)
az = model.kind("codex-azure")
check("azure requirements name the missing variables",
      kinds.missing_requirements(az, {}) == ["AZURE_OPENAI_RESOURCE or AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_MODEL_DAILY"])
check("azure base URL derives from the resource",
      kinds.Context(az, {"AZURE_OPENAI_RESOURCE": "res"}, SCRATCH).expand("{base}") ==
      "https://res.services.ai.azure.com/openai/v1")
pctx = kinds.Context(model.kind("pi-glm"), {}, SCRATCH)
check("pi --models lists provider/model once each",
      pctx.expand("{models}") == "zai-glm/glm-5.3,zai-glm/glm-5.3-flash", pctx.expand("{models}"))

# --- writers -----------------------------------------------------------------
w = os.path.join(SCRATCH, "writers")
os.makedirs(w)
cx = os.path.join(w, "codex", "glm.config.toml")
writers.write_codex(cx, "ZAI", "Z.AI", "https://example.invalid/v1", "ZAI_CODING_API_KEY", "glm-5.3")
with open(cx) as h:
    text = h.read()
check("codex overlay references env_key, never a value",
      'env_key = "ZAI_CODING_API_KEY"' in text and PLANTED not in text)
check("codex overlay is mode 600 in a 700 directory", mode(cx) == 0o600 and mode(os.path.dirname(cx)) == 0o700,
      "%o %o" % (mode(cx), mode(os.path.dirname(cx))))
check("codex overlay rewrite is idempotent",
      writers.write_codex(cx, "ZAI", "Z.AI", "https://example.invalid/v1", "ZAI_CODING_API_KEY", "glm-5.3") is False)
mine = os.path.join(w, "codex", "mine.config.toml")
with open(mine, "w") as h:
    h.write('model = "my-own"\n')
err = raises(lambda: writers.write_codex(mine, "x", "x", "u", "K", "m"), writers.WriterError)
with open(mine) as h:
    check("codex writer refuses a file it did not write", err and h.read() == 'model = "my-own"\n')
legacy = os.path.join(w, "codex", "legacy.config.toml")
with open(legacy, "w") as h:
    h.write("# Generated by coding-agents-setup-kit; do not hand-edit.\nmodel = \"old\"\n")
check("codex writer adopts the predecessor kit's overlay",
      writers.write_codex(legacy, "x", "x", "u", "K", "m") is True)

oc = os.path.join(w, "opencode.json")
with open(oc, "w") as h:
    h.write('{"provider":{"ollama":{"options":{"baseURL":"http://127.0.0.1:11434/v1"}}},"model":"ollama/x","theme":"dark"}\n')
writers.write_opencode(oc, "xai", "XAI_API_KEY", "https://api.x.ai/v1", ["grok-4.3", "grok-4.6", "grok-4.3"])
with open(oc) as h:
    d = json.load(h)
check("opencode writer keeps other providers, the global model and other keys",
      "ollama" in d["provider"] and d["model"] == "ollama/x" and d["theme"] == "dark")
check("opencode writer uses {env:KEY} and de-duplicates models",
      d["provider"]["xai"]["options"]["apiKey"] == "{env:XAI_API_KEY}" and
      d["provider"]["xai"]["whitelist"] == ["grok-4.3", "grok-4.6"])
check("opencode writer keeps a one-time backup", os.path.exists(oc + ".agentkit.bak"))
check("opencode writer is idempotent",
      writers.write_opencode(oc, "xai", "XAI_API_KEY", "https://api.x.ai/v1", ["grok-4.3", "grok-4.6"]) is False)
broken = os.path.join(w, "broken.json")
with open(broken, "w") as h:
    h.write("{not json")
err = raises(lambda: writers.write_opencode(broken, "xai", "K", "u", ["m"]), writers.WriterError)
with open(broken) as h:
    check("opencode writer refuses invalid JSON and leaves it untouched", err and h.read() == "{not json")
arr = os.path.join(w, "array.json")
with open(arr, "w") as h:
    h.write("[]")
check("opencode writer refuses a non-object file", raises(lambda: writers.write_opencode(arr, "x", "K", "u", ["m"]), writers.WriterError))

pm = os.path.join(w, "pi", "models.json")
os.makedirs(os.path.dirname(pm))
with open(pm, "w") as h:
    h.write('{"providers":{"mine":{"baseUrl":"http://x"}},"extra":1}\n')
writers.write_pi(pm, "zai-glm", "https://api.z.ai/api/coding/paas/v4", "ZAI_CODING_API_KEY", 1000000, 131072, False,
                 ["glm-5.3:sonnet", "glm-5.3:opus", "glm-5.3-flash:haiku"])
with open(pm) as h:
    d = json.load(h)
p = d["providers"]["zai-glm"]
check("pi writer stores \"$KEY\", keeps other providers", p["apiKey"] == "$ZAI_CODING_API_KEY" and "mine" in d["providers"] and d["extra"] == 1)
check("pi writer de-duplicates model ids", [m["id"] for m in p["models"]] == ["glm-5.3", "glm-5.3-flash"])
check("pi writer refuses invalid JSON",
      raises(lambda: writers.write_pi(broken, "x", "u", "K", 1, 1, False, ["m"]), writers.WriterError))

# Every shipped writer kind, with a planted key in the environment: the value
# never reaches a file.
home = os.path.join(SCRATCH, "home")
os.makedirs(home)
env = {
    "ZAI_CODING_API_KEY": PLANTED, "XAI_API_KEY": PLANTED, "AZURE_OPENAI_API_KEY": PLANTED,
    "AZURE_OPENAI_RESOURCE": "res", "AZURE_OPENAI_MODEL_DAILY": "my-deployment",
}
written = []
for name in model.kind_names():
    k = model.kind(name)
    if not k.data.get("writer"):
        continue
    wctx = kinds.Context(k, env, home)
    written.append(writers.apply(k, wctx))
leaks = []
for dirpath, _dirs, files in os.walk(home):
    for f in files:
        with open(os.path.join(dirpath, f), "rb") as h:
            if PLANTED.encode() in h.read():
                leaks.append(f)
check("all 9 provider writers run against a sandbox home", len(written) == 9 and all(os.path.exists(x) for x in written),
      str(written))
check("no writer persisted the planted key value", not leaks, str(leaks))
check("writers target each CLI's own default home",
      os.path.join(home, ".codex", "azure.config.toml") in written and
      os.path.join(home, ".config", "opencode", "opencode.json") in written and
      os.path.join(home, ".pi", "agent", "models.json") in written, str(written))
pdir = os.path.join(SCRATCH, "profile-pi")
pctx = kinds.Context(model.kind("pi-xai"), env, home, profile_dir=pdir, profile_label="@work")
check("a profile's writer targets the profile", writers.apply(model.kind("pi-xai"), pctx) == os.path.join(pdir, "models.json"))
