"""`ak env <kind> [@profile]` — the profile's environment as KEY=VALUE lines.

Purpose: let another launcher (Herdr: `herdr pane split --env KEY=VALUE …`
then `herdr agent start --kind <kind>`) start the raw CLI in a profile.

Contract (interface 1):
  * stdout carries only KEY=VALUE lines: no `export`, no quoting;
  * no secret value, ever: provider keys are not printed (the kind's
    secret-bearing variables are named on stderr instead);
  * exit 0 with no output means "the CLI's own home" (@default of a
    canonical kind).
"""

import sys

import common
import launch
from common import AkError, EXIT_USAGE

# Variables that are the kit's own bookkeeping, not the CLI's environment.
INTERNAL = ("AGENTKIT_ACTIVE_PROFILE", "AGENTKIT_REAL_HOME")


def compute(model, kind_name, head, env):
    """(lines, notes): the KEY=VALUE pairs and the stderr notes."""
    import kinds
    before = dict(env)
    prep = launch.prepare(model, kind_name, head, env, purpose="print")
    changed = {}
    for name, value in prep.env.items():
        if before.get(name) != value and name not in INTERNAL:
            changed[name] = value
    # apply_keys may have mapped a key in memory; it is never printed. When
    # it removed one (optional key, named profile), print it empty so the
    # pane cannot inherit profile 1's key.
    blank = []
    if prep.kind.key_var:
        changed.pop(prep.kind.key_var, None)
        if before.get(prep.kind.key_var) and prep.kind.key_var not in prep.env:
            blank.append(prep.kind.key_var)
    provider_env, skipped = kinds.provider_env(prep.kind, prep.ctx, include_secret=False)
    changed.update(provider_env)
    for name in blank:
        changed[name] = ""
    lines = []
    for name in sorted(changed):
        value = changed[name]
        if (common.secret_like(name) and value) or "\n" in value:
            continue
        lines.append("%s=%s" % (name, value))
    notes = []
    if skipped or prep.kind.key_var and not prep.kind.key_optional:
        names = skipped or [prep.kind.key_var]
        notes.append("%s is not printed (it carries the %s key). Launch the kind itself in the pane "
                     "instead: ak %s %s" % (", ".join(names), prep.kind.key_var, kind_name,
                                            "@" + prep.profile if prep.profile else ""))
    extra = []
    if prep.kind.data.get("args"):
        extra.append("its arguments (%s)" % " ".join(a for a in prep.kind.data["args"] if "{key}" not in a))
    if prep.kind.data.get("writer"):
        extra.append("the provider config ak writes before launch")
    if prep.kind.data.get("pre"):
        extra.append("`%s %s` before launch" % (prep.kind.executable, prep.kind.data["pre"][0]))
    if extra:
        notes.append("%s also needs %s, which an environment cannot carry: run `ak %s%s` in the pane"
                     % (kind_name, " and ".join(extra), kind_name, " @" + prep.profile if prep.profile else ""))
    return lines, notes


def main(model, args, env):
    if not args or args[0].startswith("-"):
        raise AkError("usage: ak env <kind> [@profile]", EXIT_USAGE)
    kind_name = args[0]
    if kind_name not in model.kinds:
        raise AkError("unknown kind '%s'. Kinds: %s" % (kind_name, " ".join(model.kind_names())), EXIT_USAGE)
    rest = args[1:]
    if len(rest) > 1 or (rest and not rest[0].startswith("@")):
        raise AkError("usage: ak env <kind> [@profile]", EXIT_USAGE)
    head = launch.Head()
    if rest:
        head.profile_token = rest[0]
    elif env.get("AGENTKIT_PROFILE"):
        head.profile_token = env["AGENTKIT_PROFILE"] if env["AGENTKIT_PROFILE"].startswith("@") \
            else "@" + env["AGENTKIT_PROFILE"]
        head.profile_from_env = True
    lines, notes = compute(model, kind_name, head, dict(env))
    for note in notes:
        sys.stderr.write("ak env: %s\n" % note)
    for line in lines:
        sys.stdout.write(line + "\n")
    return 0
