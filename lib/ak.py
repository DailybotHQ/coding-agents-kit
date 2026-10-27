"""ak / agentkit — the python core behind bin/ak.

    ak <kind> [@profile] [--ask | --auto] [--trust-cwd] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
    ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] [--output-format text|json] [--ask | --auto] [--trust-cwd] -- "<prompt>"
    ak env <kind> [@profile] | ak env import <file>
    ak doctor [--json]
    ak usage [<kind-or-cli>] [@profile] [-v] [--json] [--timeout SECONDS] [--no-color] (alias: ak status)
    ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--count N] [--exclude @p]... [--owner ADDR] [--json]
    ak capacity [<kind-or-cli>] [@profile] [--self] [--low PCT] [--critical PCT] [--max-age S] [--json]
    ak lease <kind-or-cli> @profile --owner ADDR [--ttl DUR] [--purpose TEXT] | ak lease release <kind> @profile --owner ADDR | ak lease ls [--json]
    ak setup probe [--json] | ak setup verify [--json] [...] | ak setup docker --ref TAG --sha256 HEX [...]
    ak profiles [ls [--json] | add <kind> @name | path <kind> @name | run <kind> @name -- <cmd…> | rm <kind> @name [--yes] | hooks <kind> @name]
    ak alias [list | add <name> <kind> [@profile] [--ask | --auto] | rm <name> | preset classic|providers [--on|--off]]
    ak install [<cli>…] [--all]
    ak last [-c | -r] | ak last ls
    ak --skill [setup | orchestrate] | --version | --help
"""

import os
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside an install

import common  # noqa: E402
import kinds  # noqa: E402
from common import AkError  # noqa: E402

USAGE = """usage:
  ak <kind> [@profile] [--ask | --auto] [--trust-cwd] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
  ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] [--output-format text|json] [--ask | --auto] [--trust-cwd] -- "<prompt>"
  ak env <kind> [@profile] | ak env import <file>
  ak doctor [--json]
  ak usage [<kind-or-cli>] [@profile] [-v] [--json] [--timeout SECONDS] [--no-color] (alias: ak status)
  ak pick <kind-or-cli> [@profile] [--model NAME] [--need WIN:PCT]... [--count N] [--exclude @p]... [--owner ADDR] [--json]
  ak capacity [<kind-or-cli>] [@profile] [--self] [--low PCT] [--critical PCT] [--max-age S] [--json]
  ak lease <kind-or-cli> @profile --owner ADDR [--ttl DUR] [--purpose TEXT] | ak lease release <kind> @profile --owner ADDR | ak lease ls [--json]
  ak setup probe [--json] | ak setup verify [--json] [--cli LIST] [--profile CLI=@a,@b] [--keys NAMES] [--expect-posture auto|ask]
  ak profiles [ls [--json] | add <kind> @name | path <kind> @name | run <kind> @name -- <cmd…> | rm <kind> @name [--yes] | hooks <kind> @name]
  ak alias [list | add <name> <kind> [@profile] [--ask | --auto] | rm <name> | preset classic|providers [--on|--off]]
  ak install [<cli>…] [--all]
  ak last [-c | -r] | ak last ls      (back to the last ak launch in this directory)
  ak --skill [setup | orchestrate] | --version | --help

Kinds: {kinds}
Autonomy by default: every launch adds the CLI's own autonomy flag. Opt out
with --ask or AGENTKIT_PERMISSIONS=ask (meant for hosts; autonomy is meant for
disposable or sandboxed environments). Docs: {root}/docs/
"""


def _cli_label(kind):
    """The CLI, and its command when that is another name: `antigravity (agy)`."""
    if kind.executable == kind.cli_name:
        return kind.cli_name
    return "%s (%s)" % (kind.cli_name, kind.executable)


def list_kinds(model):
    names = model.kind_names()
    wk = max([len(n) for n in names] + [len("KIND")]) + 1
    wc = max([len(_cli_label(model.kind(n))) for n in names] + [len("CLI")]) + 1
    print("%-*s %-*s %-10s %s" % (wk, "KIND", wc, "CLI", "PROVIDER", "INSTALLED"))
    for name in names:
        kind = model.kind(name)
        exe = common.resolve_executable(kind.cli)
        print("%-*s %-*s %-10s %s" % (wk, name, wc, _cli_label(kind), kind.provider_name or "-", exe or "no"))
    print("\nRun: ak <kind> [@profile]   ·   ak --help")
    return 0


SKILLS = {"": "agentkit", "agentkit": "agentkit", "setup": "agentkit-setup", "agentkit-setup": "agentkit-setup",
          "orchestrate": "agentkit-orchestrate", "agentkit-orchestrate": "agentkit-orchestrate"}


def print_skill(which=""):
    if which not in SKILLS:
        raise AkError("unknown skill '%s'. Skills: agentkit (default), setup, orchestrate" % which)
    path = os.path.join(common.KIT_ROOT, "skills", SKILLS[which], "SKILL.md")
    try:
        with open(path) as handle:
            sys.stdout.write(handle.read())
    except OSError:
        raise AkError("the bundled skill is missing (%s); reinstall the kit" % path, common.EXIT_INTERNAL)
    return 0


def main(argv):
    env = dict(os.environ)
    common.load_env_file(env)
    # The launcher's marker is bookkeeping: no child (CLI, nested ak,
    # `ak profiles run`) ever sees it, so a nested ak loads the file again.
    env.pop("AGENTKIT_ENV_LOADED", None)
    os.environ.clear()
    os.environ.update(env)
    if not argv:
        return list_kinds(kinds.load())
    first, rest = argv[0], argv[1:]
    if first in ("--version", "-V", "version"):
        print("agentkit %s (interface %d)" % (common.VERSION, common.INTERFACE))
        return 0
    if first in ("--help", "-h", "help"):
        model = kinds.load()
        sys.stdout.write(USAGE.format(kinds=" ".join(model.kind_names()), root=common.KIT_ROOT))
        return 0
    if first == "--skill":
        if len(rest) > 1:
            raise AkError("usage: ak --skill [setup | orchestrate]")
        return print_skill(rest[0] if rest else "")
    model = kinds.load()
    if first == "run":
        import run
        return run.main(model, rest, env)
    if first == "env":
        import envcmd
        return envcmd.main(model, rest, env)
    if first == "doctor":
        import doctor
        return doctor.main(model, rest, env)
    if first in ("usage", "status"):
        import usage
        return usage.main(model, rest, env)
    if first == "pick":
        import pick
        return pick.main(model, rest, env)
    if first == "capacity":
        import capacity
        return capacity.main(model, rest, env)
    if first == "lease":
        import lease
        return lease.main(model, rest, env)
    if first == "setup":
        import setup
        return setup.main(model, rest, env)
    if first == "profiles":
        import profiles
        return profiles.main(model, rest, env)
    if first == "alias":
        import aliases
        return aliases.main(model, rest, env)
    if first == "install":
        import installer
        return installer.main(model, rest, env)
    if first == "last":
        import last
        return last.main(model, rest, env)
    if first.startswith("-"):
        raise AkError("unknown option '%s'. See: ak --help" % first)
    first = model.canonical(first)          # `ak agy` is `ak antigravity`
    if first not in model.kinds:
        raise AkError("unknown kind '%s'. Kinds: %s" % (first, " ".join(model.kind_names())))
    import launch
    return launch.launch(model, first, rest, env)


def entry():
    try:
        code = main(sys.argv[1:])
    except AkError as exc:
        common.warn(str(exc))
        code = exc.code
    except kinds.KindsError as exc:
        common.warn(str(exc))
        code = common.EXIT_USAGE if "unknown" in str(exc) else common.EXIT_INTERNAL
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:  # pragma: no cover - a bug in the kit
        if os.environ.get("AGENTKIT_DEBUG") == "1":
            raise
        common.warn("internal error: %s: %s (rerun with AGENTKIT_DEBUG=1 for a traceback)"
                    % (exc.__class__.__name__, exc))
        code = common.EXIT_INTERNAL
    sys.stdout.flush()
    sys.exit(code)


if __name__ == "__main__":
    entry()
