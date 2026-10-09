"""ak / agentkit — the python core behind bin/ak.

    ak <kind> [@profile] [--ask | --auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
    ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] [--output-format text|json] [--ask | --auto] -- "<prompt>"
    ak env <kind> [@profile]
    ak doctor [--json]
    ak profiles [ls | add <kind> @name | path <kind> @name | run <kind> @name -- <cmd…> | rm <kind> @name [--yes] | hooks <kind> @name]
    ak alias [list | add <name> <kind> [@profile] [--ask | --auto] | rm <name> | preset classic [--on|--off]]
    ak install [<cli>…] [--all]
    ak --skill | --version | --help
"""

import os
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside an install

import common  # noqa: E402
import kinds  # noqa: E402
from common import AkError  # noqa: E402

USAGE = """usage:
  ak <kind> [@profile] [--ask | --auto] [-c | --continue | -r [id] | --resume [id] | -l] [--] [cli args…]
  ak run <kind> [@profile] [--cwd DIR] [--timeout SECONDS] [--output-format text|json] [--ask | --auto] -- "<prompt>"
  ak env <kind> [@profile]
  ak doctor [--json]
  ak profiles [ls | add <kind> @name | path <kind> @name | run <kind> @name -- <cmd…> | rm <kind> @name [--yes] | hooks <kind> @name]
  ak alias [list | add <name> <kind> [@profile] [--ask | --auto] | rm <name> | preset classic [--on|--off]]
  ak install [<cli>…] [--all]
  ak --skill | --version | --help

Kinds: {kinds}
Autonomy by default: every launch adds the CLI's own autonomy flag. Opt out
with --ask or AGENTKIT_PERMISSIONS=ask (meant for hosts; autonomy is meant for
disposable or sandboxed environments). Docs: {root}/docs/
"""


def list_kinds(model):
    print("%-16s %-9s %-10s %s" % ("KIND", "CLI", "PROVIDER", "INSTALLED"))
    for name in model.kind_names():
        kind = model.kind(name)
        exe = common.resolve_executable(kind.cli)
        print("%-16s %-9s %-10s %s" % (name, kind.cli_name, kind.provider_name or "-", exe or "no"))
    print("\nRun: ak <kind> [@profile]   ·   ak --help")
    return 0


def print_skill():
    path = os.path.join(common.KIT_ROOT, "skills", "agentkit", "SKILL.md")
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
        return print_skill()
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
    if first == "profiles":
        import profiles
        return profiles.main(model, rest, env)
    if first == "alias":
        import aliases
        return aliases.main(model, rest, env)
    if first == "install":
        import installer
        return installer.main(model, rest, env)
    if first.startswith("-"):
        raise AkError("unknown option '%s'. See: ak --help" % first)
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
