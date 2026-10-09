"""The kinds model: providers.toml loaded, validated and resolved.

Everything `ak` knows about a CLI, a provider or a kind comes from
providers.toml through this module; nothing here names a specific CLI
except the two isolation strategies and the extractors, which the data
selects by name.

Secret discipline: the only secret this module ever handles is a
provider key, reached through the template {key}. It is resolved only when
the caller asks for the launch environment (`allow_secret=True`), never
for anything that is printed (`ak env`, doctor, errors, `show`).
"""

import os
import sys

try:  # python >= 3.11
    import tomllib as _toml
except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    import tomlmini as _toml

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROVIDERS_FILE = os.path.join(KIT_ROOT, "providers.toml")
SCHEMA = 1

SEGMENTS = ("provider", "session", "auto", "json", "timeout")
ISOLATIONS = ("env", "cursor-home", "xdg")
WRITER_TYPES = ("codex", "opencode", "pi")
RESULT_EXTRACTORS = ("json-result", "codex-jsonl", "opencode-jsonl", "pi-jsonl", "cline-jsonl")
INSTALL_CHANNELS = ("script", "npm")
SESSION_KEYS = ("continue", "resume", "pick", "list", "last", "standalone",
                "pick_error", "continue_strategy")
CONTINUE_STRATEGIES = ("cline-history",)


class KindsError(Exception):
    """A problem a user can fix (unknown kind, missing variable, bad data).
    The message never carries a secret value."""


class SecretReference(KindsError):
    """A template needed {key} where secrets are not allowed."""


# ------------------------------------------------------------ templates

def _split_template(text, start):
    """Parse one {…} at text[start] == '{'. Returns (name, default|None, end)."""
    i = start + 1
    n = len(text)
    name_start = i
    while i < n and text[i] not in "}:":
        if text[i] == "{":
            raise KindsError("bad template %r: '{' inside a name" % text)
        i += 1
    if i >= n:
        raise KindsError("bad template %r: unclosed '{'" % text)
    name = text[name_start:i]
    if not name:
        raise KindsError("bad template %r: empty name" % text)
    if text[i] == "}":
        return name, None, i + 1
    if not text.startswith(":-", i):
        raise KindsError("bad template %r: expected ':-' after %r" % (text, name))
    i += 2
    depth = 1
    default_start = i
    while i < n:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return name, text[default_start:i], i + 1
        i += 1
    raise KindsError("bad template %r: unclosed default" % text)


def template_names(text):
    """Every name a template may read (defaults included)."""
    names = []
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return names
        name, default, end = _split_template(text, j)
        names.append(name)
        if default is not None:
            names.extend(template_names(default))
        i = end


def references_secret(value):
    """True when a template (or a list of them) can read {key}."""
    if isinstance(value, list):
        return any(references_secret(v) for v in value)
    return isinstance(value, str) and "key" in template_names(value)


def expand(text, lookup):
    """Expand {name} / {name:-default}; lookup(name) -> str or None."""
    out = []
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        name, default, end = _split_template(text, j)
        value = lookup(name)
        if (value is None or value == "") and default is not None:
            value = expand(default, lookup)
        out.append(value or "")
        i = end
    result = "".join(out)
    return result


def expand_home(path, home):
    if path == "~":
        return home
    if path.startswith("~/"):
        return os.path.join(home, path[2:])
    return path


# ---------------------------------------------------------------- model

def load(path=None):
    path = path or PROVIDERS_FILE
    try:
        with open(path, "rb") as handle:
            data = _toml.load(handle)
    except OSError as exc:
        raise KindsError("cannot read %s: %s" % (path, exc.strerror))
    except ValueError as exc:  # tomllib.TOMLDecodeError and TOMLError
        raise KindsError("%s is not valid TOML: %s" % (path, exc))
    model = Model(data, path)
    model.validate()
    return model


class Model(object):
    def __init__(self, data, path):
        self.data = data
        self.path = path
        self.clis = data.get("clis", {})
        self.providers = data.get("providers", {})
        self.kinds = data.get("kinds", {})

    # -- validation: every rule a data entry must follow ------------------
    def validate(self):
        problems = []

        def bad(msg):
            problems.append(msg)

        if self.data.get("schema") != SCHEMA:
            bad("schema must be %d" % SCHEMA)
        for cname, cli in sorted(self.clis.items()):
            where = "clis.%s" % cname
            for field in ("name", "executable", "isolation", "auto", "interactive", "roots"):
                if field not in cli:
                    bad("%s: missing %s" % (where, field))
            if cli.get("isolation") not in ISOLATIONS:
                bad("%s: isolation must be one of %s" % (where, ", ".join(ISOLATIONS)))
            if cli.get("isolation") == "env" and not cli.get("home_env"):
                bad("%s: isolation 'env' needs home_env" % where)
            roots = cli.get("roots", {})
            if "home" not in roots:
                bad("%s.roots: missing home" % where)
            for rname, root in roots.items():
                if not isinstance(root, dict) or "default" not in root or "profile" not in root:
                    bad("%s.roots.%s: needs default and profile" % (where, rname))
            for seg in cli.get("interactive", []):
                if seg.startswith("{") and seg.strip("{}") not in ("provider", "session", "auto"):
                    bad("%s.interactive: unknown segment %s" % (where, seg))
            session = cli.get("session", {})
            for key in session:
                if key not in SESSION_KEYS:
                    bad("%s.session: unknown key %s" % (where, key))
            if "continue" not in session and session.get("continue_strategy") not in CONTINUE_STRATEGIES:
                bad("%s.session: needs continue or a known continue_strategy" % where)
            if session.get("last") not in (None, "continue", "list"):
                bad("%s.session.last must be continue or list" % where)
            if session.get("last") == "list" and "list" not in session:
                bad("%s.session: last = list needs list" % where)
            run = cli.get("run", {})
            for field in ("argv", "json", "result"):
                if field not in run:
                    bad("%s.run: missing %s" % (where, field))
            if run.get("result") not in RESULT_EXTRACTORS:
                bad("%s.run.result must be one of %s" % (where, ", ".join(RESULT_EXTRACTORS)))
            if "{prompt}" not in run.get("argv", []):
                bad("%s.run.argv: needs {prompt}" % where)
            if references_secret(cli.get("auto", [])) or references_secret(run.get("argv", [])):
                bad("%s: {key} is only allowed in a kind's env, args or pre" % where)
            install = cli.get("install", {})
            if install.get("channel") not in INSTALL_CHANNELS:
                bad("%s.install.channel must be one of %s" % (where, ", ".join(INSTALL_CHANNELS)))
            if install.get("channel") == "script" and not str(install.get("url", "")).startswith("https://"):
                bad("%s.install.url must be https" % where)
            if install.get("channel") == "npm" and not install.get("package"):
                bad("%s.install: npm needs package" % where)
            if not install.get("version") and not install.get("unpinned"):
                bad("%s.install: pin a version or state why it cannot be pinned (unpinned)" % where)
            for ref in cli.get("login", {}).get("files", []) + cli.get("hooks", {}).get("files", []):
                if ref.split(":", 1)[0] not in roots:
                    bad("%s: %s names an unknown root" % (where, ref))
        for pname, prov in sorted(self.providers.items()):
            where = "providers.%s" % pname
            if not prov.get("key", "").isupper():
                bad("%s: key must be an upper-case variable name" % where)
            for var in prov.get("vars", {}).values():
                if references_secret(var):
                    bad("%s.vars: {key} is not allowed in a variable" % where)
        for kname, kind in sorted(self.kinds.items()):
            where = "kinds.%s" % kname
            cli = self.clis.get(kind.get("cli"))
            if cli is None:
                bad("%s: unknown cli %r" % (where, kind.get("cli")))
                continue
            if kind.get("provider") and kind["provider"] not in self.providers:
                bad("%s: unknown provider %r" % (where, kind["provider"]))
            if not kname.startswith(kind["cli"]):
                bad("%s: a kind is named <cli> or <cli>-<provider>" % where)
            uses_key = references_secret(list(kind.get("env", {}).values())) \
                or references_secret(kind.get("args", [])) or references_secret(kind.get("pre", []))
            if uses_key and not kind.get("provider"):
                bad("%s: {key} needs a provider" % where)
            if (references_secret(kind.get("args", [])) or references_secret(kind.get("pre", []))) \
                    and not cli.get("secret_argv"):
                bad("%s: a key on the command line is only allowed for a CLI marked secret_argv" % where)
            writer = kind.get("writer")
            if writer is not None:
                if writer.get("type") not in WRITER_TYPES:
                    bad("%s.writer.type must be one of %s" % (where, ", ".join(WRITER_TYPES)))
                if not kind.get("provider"):
                    bad("%s.writer needs a provider" % where)
                for value in writer.values():
                    if references_secret(value if isinstance(value, (list, str)) else ""):
                        bad("%s.writer: a writer never receives {key}" % where)
        if problems:
            raise KindsError("%s: %s" % (self.path, "; ".join(problems)))

    # -- lookups ----------------------------------------------------------
    def kind_names(self):
        return sorted(self.kinds)

    def cli_names(self):
        return sorted(self.clis)

    def kind(self, name):
        if name not in self.kinds:
            raise KindsError("unknown kind '%s'. Kinds: %s" % (name, " ".join(self.kind_names())))
        return Kind(self, name)

    def cli_of(self, name):
        """The CLI family for a kind or CLI name (claude-glm -> claude)."""
        if name in self.clis:
            return name
        if name in self.kinds:
            return self.kinds[name]["cli"]
        raise KindsError("unknown CLI or kind '%s'. CLIs: %s" % (name, " ".join(self.cli_names())))


class Kind(object):
    def __init__(self, model, name):
        self.model = model
        self.name = name
        self.data = model.kinds[name]
        self.cli_name = self.data["cli"]
        self.cli = model.clis[self.cli_name]
        self.provider_name = self.data.get("provider")
        self.provider = model.providers.get(self.provider_name) if self.provider_name else None

    @property
    def executable(self):
        return self.cli["executable"]

    @property
    def key_var(self):
        return self.provider["key"] if self.provider else None

    @property
    def key_optional(self):
        return bool(self.data.get("key_optional"))

    def static(self):
        """Everything about the kind that is safe to print (no env values)."""
        return {
            "kind": self.name,
            "cli": self.cli_name,
            "executable": self.executable,
            "herdr_kind": self.cli.get("herdr_kind"),
            "provider": self.provider_name,
            "key": self.key_var,
            "key_optional": self.key_optional,
            "auto": list(self.cli["auto"]),
            "isolation": self.cli["isolation"],
            "home_env": self.cli.get("home_env"),
        }


# -------------------------------------------------------------- resolve

class Context(object):
    """Variable lookup for one launch: env (upper case), provider and kind
    variables, roots, and the per-call specials (id, prompt, …)."""

    def __init__(self, kind, env, home, profile_dir=None, profile_label="@default",
                 specials=None, allow_secret=False):
        self.kind = kind
        self.env = env
        self.home = home
        self.profile_dir = profile_dir
        self.profile_label = profile_label
        self.specials = dict(specials or {})
        self.allow_secret = allow_secret
        self._vars = {}
        self._resolving = set()

    def root(self, name):
        roots = self.kind.cli["roots"]
        if name not in roots:
            raise KindsError("%s has no root %r" % (self.kind.cli_name, name))
        entry = roots[name]
        text = entry["profile"] if self.profile_dir else entry["default"]
        return os.path.normpath(expand_home(self.expand(text), self.home))

    def ref_path(self, ref):
        """'root:relative/path' -> absolute path."""
        root, _, rel = ref.partition(":")
        return os.path.join(self.root(root), rel)

    def lookup(self, name):
        if name == "key":
            if not self.allow_secret:
                raise SecretReference("this value needs the provider key, which is never printed")
            var = self.kind.key_var
            return self.env.get(var, "") if var else ""
        if name.isupper() or name[0].isupper():
            return self.env.get(name)
        if name == "dir":
            return self.profile_dir or ""
        if name == "kind":
            return self.kind.name
        if name == "profile":
            return self.profile_label
        if name.startswith("root."):
            return self.root(name[5:])
        if name in self.specials:
            return self.specials[name]
        if name in self._vars:
            return self._vars[name]
        source = None
        if name == "models" and self.kind.data.get("writer", {}).get("type") == "pi":
            return self._pi_models()
        if self.kind.provider and name in self.kind.provider.get("vars", {}):
            source = self.kind.provider["vars"][name]
        if source is None:
            raise KindsError("kinds.%s: template variable {%s} is not defined" % (self.kind.name, name))
        if name in self._resolving:
            raise KindsError("kinds.%s: variable {%s} refers to itself" % (self.kind.name, name))
        self._resolving.add(name)
        try:
            value = self.expand(source)
        finally:
            self._resolving.discard(name)
        self._vars[name] = value
        return value

    def _pi_models(self):
        writer = self.kind.data["writer"]
        seen = []
        for spec in writer.get("models", []):
            mid = self.expand(spec).partition(":")[0]
            ref = "%s/%s" % (writer["provider_id"], mid)
            if mid and ref not in seen:
                seen.append(ref)
        return ",".join(seen)

    def expand(self, text):
        return expand(text, self.lookup)

    def expand_list(self, items, segments=None):
        """Expand an argv template; whole-element {segment} -> list."""
        out = []
        for item in items:
            if item.startswith("{") and item.endswith("}") and item[1:-1] in SEGMENTS:
                out.extend((segments or {}).get(item[1:-1], []))
            else:
                out.append(self.expand(item))
        return out


def missing_requirements(kind, env):
    """Variables a provider requires that are not set, as display names."""
    missing = []
    if not kind.provider:
        return missing
    for req in kind.provider.get("require", []):
        options = req.split("|")
        if not any(env.get(opt) for opt in options):
            missing.append(" or ".join(options))
    return missing


def provider_env(kind, ctx, include_secret):
    """The kind's env entries, expanded. Entries that read {key} are
    included only when include_secret; empty values are dropped. Returns
    (env dict, names of skipped secret entries)."""
    env = {}
    skipped = []
    for name, template in sorted(kind.data.get("env", {}).items()):
        if references_secret(template) and not include_secret:
            skipped.append(name)
            continue
        value = ctx.expand(template)
        if value:
            env[name] = value
    return env, skipped


def main(argv):
    """Debug and test entry: list | show <kind> | check [file]."""
    import json
    cmd = argv[0] if argv else "list"
    try:
        if cmd == "check":
            load(argv[1] if len(argv) > 1 else None)
            print("ok")
            return 0
        model = load()
        if cmd == "list":
            print("\n".join(model.kind_names()))
            return 0
        if cmd == "show" and len(argv) == 2:
            print(json.dumps(model.kind(argv[1]).static(), indent=2, sort_keys=True))
            return 0
    except KindsError as exc:
        sys.stderr.write("kinds: %s\n" % exc)
        return 1
    sys.stderr.write("usage: kinds.py list | show <kind> | check [file]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
