"""`ak update [<kind-or-cli>…] [--version VERSION] [--take-over] [--json]`.

Vendor releases move faster than kit releases: providers.toml pins one
version per CLI and a kit release moves it. `ak update` brings a CLI to the
vendor's newest release on this machine without waiting for that bump, with
exactly the verification `ak install` applies:

  1. discover  the newest version from the vendor (providers.toml
     `install.latest`: kind `npm` reads the registry's dist-tags.latest
     document; kind `manifest` reads the vendor's channel file naming the
     newest version and a per-version manifest.json whose platform tokens
     are mapped back through `install.platforms`). A CLI without a
     `latest` table is skipped: move its pin with scripts/update-pins.sh.
  2. verify    npm: the registry's dist.integrity (sha512). manifest: the
     manifest.json digests. A mismatch refuses before anything is
     installed and before the pin moves.
  3. install   through the channel itself: npm install -g of the verified
     tarball; the verified binary written over ~/.local/bin/<executable>
     (a regular file there is backed up to <name>.agentkit-orig first).
  4. resolve   the update counts only when PATH resolves the new release.
     `ak update` never silently replaces an entry it did not make: a
     vendor-managed symlink (codex's standalone layout, Claude's native
     installer) is replaced only with `--take-over`, which prints what it
     pointed at; a foreign regular file is backed up, never deleted. This
     is the gap that makes a vendor's in-CLI "update now" action useless
     under ak: it updates a copy PATH does not resolve. An install whose
     copy stays shadowed is reported as such and the pin does not move.
  5. re-pin    write the verified version and digests back into this kit's
     providers.toml (a .bak copy is kept first, and the file is parsed
     before it replaces the old one), so doctor, `ak install` and the next
     `ak update` describe the same pin.

A discovered version older than the pin is refused — pass --version to name
a downgrade on purpose. A CLI whose PATH copy already is the discovered
version is reported current and only re-pins. Channels without a vendor
manifest (cursor, grok, antigravity: trust-on-first-use digests) are never
updated here. --json prints one update-v1 document (docs/schema/update-v1.json);
everything the install itself prints goes to stderr in that mode.
"""

import contextlib
import json
import os
import re
import shutil
import sys
import tempfile

import common
import installer
import kinds
from common import AkError, EXIT_NOT_READY, EXIT_OK, EXIT_USAGE

SCHEMA = "update-v1"
USAGE = "usage: ak update [<kind-or-cli>...] [--version VERSION] [--take-over] [--json]"

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)(\+[0-9A-Za-z.-]+)?$")


def parse_args(args):
    """The update options: named kinds/CLIs, an explicit version, the
    take-over grant and the JSON surface."""
    opts = {"names": [], "version": None, "take_over": False, "json": False}
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg in ("-h", "--help"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--take-over":
            opts["take_over"] = True
        elif arg == "--version":
            if not rest:
                raise AkError("%s\n--version needs a value, e.g. ak update codex --version 0.169.0" % USAGE, EXIT_USAGE)
            opts["version"] = rest.pop(0)
        elif arg.startswith("-"):
            raise AkError("unknown option '%s'. See: ak update --help" % arg, EXIT_USAGE)
        else:
            opts["names"].append(arg)
    return opts


def _vkey(text):
    """(key, exact) from a --version banner: the FIRST token must be a
    version (an optional v, optional +build metadata), so prose like
    "requires Node 99.0.0" parses as nothing instead of a newer release.
    exact is False when the token carries a suffix (0.169.0-alpha); only an
    exact match may take the no-install shortcut, and ordering stays
    conservative on the numeric part. (None, False) when unparsable."""
    token = (text or "").strip().split()
    found = _VERSION_RE.match(token[0]) if token else None
    if not found:
        return None, False
    key = tuple(int(part) for part in found.group(1).split("."))
    return key, found.group(2) is None


def _read_download(url, env, binary):
    """The body of an https URL through the installer's download (curl, or
    the stdlib fallback), as bytes or text; AkError when it fails."""
    tmpdir = tempfile.mkdtemp(prefix="agentkit-update-")
    try:
        dest = os.path.join(tmpdir, "doc")
        if not installer._download(url, dest, env):
            raise AkError("download failed: %s" % url, EXIT_NOT_READY)
        with open(dest, "rb") as fh:
            data = fh.read()
        return data if binary else data.decode("utf-8", "replace")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _fetch_json(url, env):
    try:
        return json.loads(_read_download(url, env, binary=False))
    except ValueError as exc:
        raise AkError("the document at %s is not valid JSON (%s)" % (url, exc), EXIT_NOT_READY)


def discover(inst, explicit, env):
    """(version, verification) for the release to install: the vendor's
    newest per `install.latest`, or the named --version with its digests.
    Manifest digests come back keyed by this kit's platform names."""
    latest = inst.get("latest") or {}
    kind_ = latest.get("kind")
    if kind_ == "npm":
        url = "%s/%s/%s" % (installer.NPM_REGISTRY, inst["package"], explicit or "latest")
        doc = _fetch_json(url, env)
        version = explicit or doc.get("version")
        integrity = (doc.get("dist") or {}).get("integrity")
        if not version or not integrity:
            raise AkError("the registry document for %s names no version or integrity" % inst["package"], EXIT_NOT_READY)
        return str(version), {"integrity": str(integrity)}
    if kind_ == "manifest":
        version = explicit or _read_download(latest["channel"], env, binary=False).strip()
        if not version or "/" in version or "{" in version or len(version) > 40:
            raise AkError("the channel file at %s names no version (got %r)" % (latest["channel"], version[:40]), EXIT_NOT_READY)
        manifest = _fetch_json(latest["manifest"].replace("{version}", version), env)
        vendors = manifest.get("platforms") or {}
        platforms = inst.get("platforms") or {}
        digests = {}
        for plat, token in platforms.items():
            checksum = (vendors.get(token) or {}).get("checksum")
            if checksum:
                digests[plat] = checksum
        missing = [plat for plat in platforms if plat not in digests]
        if missing:
            raise AkError("the manifest for %s has no digest for %s; nothing was installed and the pin is unchanged"
                          % (version, ", ".join(missing)), EXIT_NOT_READY)
        if not digests:
            raise AkError("the manifest for %s names no digest for this kit's platforms" % version, EXIT_NOT_READY)
        return str(version), {"sha256": digests}
    raise AkError("no vendor discovery for this channel; move the pin with scripts/update-pins.sh", EXIT_USAGE)


def _resolved_version(exe):
    """The first line of `<exe> --version`, or '' when it prints nothing."""
    if not exe:
        return ""
    out = common._probe([exe, "--version"], timeout=5).strip()
    return out.splitlines()[0] if out else ""


def _npm_prefix_bin(env):
    """The directory npm installs global packages into (its prefix's bin),
    or None when npm does not say."""
    npm = common.which("npm", env)
    if not npm:
        return None
    out = common._probe([npm, "config", "get", "prefix"], timeout=10).strip().splitlines()
    prefix = out[0].strip() if out else ""
    if not prefix or not os.path.isdir(prefix):
        return None
    if common.os_name() == "windows":
        return prefix
    return os.path.join(prefix, "bin")


def update_one(model, cli_name, opts, env):
    """One CLI's update result (a dict); expected outcomes never raise."""
    cli = model.clis[cli_name]
    inst = dict(cli.get("install") or {})
    pin = str(inst.get("version") or "")
    result = {"cli": cli_name, "channel": inst.get("channel", ""), "from_pin": pin,
              "to_version": None, "resolution": "", "pin_written": False, "status": "failed", "note": ""}
    if not inst:
        result["status"] = "skipped"
        result["note"] = "not installable here"
        return result
    if inst.get("channel") == "tarball":
        result["status"] = "skipped"
        result["note"] = "no vendor discovery for this channel; move the pin with scripts/update-pins.sh"
        return result
    before_exe = common.resolve_executable(cli, env)
    before = _resolved_version(before_exe)
    try:
        new_version, verification = discover(inst, opts["version"], env)
    except AkError as exc:
        result["status"] = "skipped" if exc.code == EXIT_USAGE else "failed"
        result["note"] = str(exc)
        return result
    result["to_version"] = new_version
    new_key, _ = _vkey(new_version)
    pin_key, _ = _vkey(pin)
    if not opts["version"] and new_key is not None and pin_key is not None and new_key < pin_key:
        result["status"] = "skipped"
        result["note"] = "refusing a downgrade: the pin (%s) is newer than %s; pass --version to name it" % (pin, new_version)
        return result
    resolved_key, resolved_exact = _vkey(before)
    if resolved_key is not None and new_key is not None and resolved_key > new_key:
        result["status"] = "skipped"
        result["note"] = "PATH already resolves %s, newer than %s; refusing to downgrade it" % (before, new_version)
        return result
    if resolved_exact and new_key is not None and resolved_key == new_key:
        # The machine already runs exactly this release; nothing to install —
        # at most the pin moves (a vendor self-update outran the kit's pin).
        result["status"] = "current"
        return _repin(result, model, cli_name, inst, new_version, verification)

    # The binary channel writes ~/.local/bin/<executable>: a vendor-managed
    # symlink there (Claude's native installer) is replaced only on purpose,
    # and a foreign regular file is backed up, never deleted.
    extra = ""
    dest = os.path.join(installer.bin_dir(), cli["executable"]) if inst.get("channel") == "binary" else None
    if dest is not None and os.path.islink(dest):
        if not opts["take_over"]:
            result["status"] = "skipped"
            result["note"] = "%s is a link ak did not make (-> %s); rerun with --take-over to replace it" % (
                dest, os.readlink(dest))
            return result
        extra = " (took over %s, was a link to %s)" % (dest, os.readlink(dest))
    elif dest is not None and os.path.exists(dest):
        backup = dest + ".agentkit-orig"
        if not os.path.exists(backup):
            shutil.copy2(dest, backup)
            extra = " (the previous %s is kept at %s)" % (dest, backup)

    cand = dict(inst)
    cand["version"] = new_version
    cand.update(verification)
    ienv = installer.installer_env(env)
    tmpdir = tempfile.mkdtemp(prefix="agentkit-update-")
    try:
        if inst.get("channel") == "npm":
            ok = installer._install_npm(cli_name, cand, tmpdir, ienv, False)
        else:
            ok = installer._install_binary(cli_name, cli, cand, installer.platform_key(), tmpdir, ienv, False)
    except (AkError, OSError) as exc:
        result["note"] = "refused — %s" % exc
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        result["note"] = "the install failed; the pin is unchanged"
        return result

    # The update counts only when PATH resolves the new release. An npm
    # install lands in npm's prefix; when an earlier PATH entry still wins
    # with a vendor-managed link, take it over on purpose — a regular file
    # is never replaced by a link.
    after = common.resolve_executable(cli, env)
    after_version = _resolved_version(after)
    if inst.get("channel") == "npm" and opts["take_over"] and common.os_name() != "windows":
        prefix_bin = _npm_prefix_bin(ienv)
        expected = os.path.join(prefix_bin, cli["executable"]) if prefix_bin else ""
        if expected and after and os.path.realpath(after) != os.path.realpath(expected) \
                and os.path.islink(after) and os.path.exists(expected):
            os.remove(after)
            os.symlink(expected, after)
            after = expected
            after_version = _resolved_version(after)
            extra = " (took over %s, now a link to %s)" % (after, expected)
    result["resolution"] = after or ""
    effective, _ = _vkey(after_version)
    if after is None or (new_key is not None and effective is not None and effective < new_key):
        # A parseable older banner is a shadowed install (the gap that makes
        # a vendor's in-CLI update a lie); an unparsable banner is trusted to
        # the verification that already happened.
        result["status"] = "skipped"
        result["note"] = "installed %s, but PATH still resolves %s%s; rerun with --take-over" % (
            new_version, after_version or "nothing", (" at %s" % after) if after else "")
        return result
    if after_version:
        result["note"] = "%s -> %s%s" % (before or "?", after_version, extra)
    elif extra:
        result["note"] = extra.strip()
    result["status"] = "updated"
    return _repin(result, model, cli_name, inst, new_version, verification)


def _repin(result, model, cli_name, inst, new_version, verification):
    """Move the pin to the verified release when it differs; the caller has
    already set the final status (current | updated) and this only records
    a failure when the pin cannot move."""
    changed = new_version != str(inst.get("version") or "")
    if verification.get("integrity") and verification["integrity"] != inst.get("integrity"):
        changed = True
    for plat, digest in (verification.get("sha256") or {}).items():
        if digest != (inst.get("sha256") or {}).get(plat):
            changed = True
    if changed:
        try:
            _write_pin(model, cli_name, new_version, verification)
            result["pin_written"] = True
        except AkError as exc:
            result["status"] = "failed"
            result["note"] = (result["note"] + " " if result["note"] else "") + "the pin did not move: %s" % exc
            return result
    return result


def _write_pin(model, cli_name, new_version, verification):
    """Move the pin in this kit's providers.toml to the verified release:
    the version and, per channel, the fetched digests (keyed by this kit's
    platform names, every pinned platform covered). The previous file is
    kept as providers.toml.bak; the new text is parsed before it replaces
    the old one.
    """
    if verification.get("sha256"):
        platforms = list((model.clis[cli_name].get("install") or {}).get("platforms", {}).keys())
        missing = [plat for plat in platforms if not verification["sha256"].get(plat)]
        if missing:
            raise AkError("no fetched digest for %s; the pin is unchanged" % ", ".join(missing), common.EXIT_INTERNAL)
    path = os.path.join(common.KIT_ROOT, "providers.toml")
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines(keepends=True)
    header = "[clis.%s.install]" % cli_name
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            break
    if start is None:
        raise AkError("%s not found in %s" % (header, path), common.EXIT_INTERNAL)
    sha_line = ""
    if verification.get("sha256"):
        platforms = list((model.clis[cli_name].get("install") or {}).get("platforms", {}).keys())
        sha_line = "sha256 = { %s }\n" % ", ".join(
            '%s = "%s"' % (plat, verification["sha256"][plat]) for plat in platforms)
    section_end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("["):
            section_end = i
            break
    for i in range(start, section_end):
        if lines[i].startswith("version = "):
            lines[i] = 'version = "%s"\n' % new_version
        elif lines[i].startswith("integrity = ") and verification.get("integrity"):
            lines[i] = 'integrity = "%s"\n' % verification["integrity"]
        elif lines[i].startswith("sha256 = ") and sha_line:
            lines[i] = sha_line
    text = "".join(lines)
    try:  # never replace a providers.toml that does not parse
        try:
            import tomllib as _toml
            _toml.loads(text)
        except ImportError:
            import tomlmini
            tomlmini.loads(text)
    except Exception as exc:
        raise AkError("the edited providers.toml does not parse (%s); nothing was written" % exc, common.EXIT_INTERNAL)
    backup = path + ".bak"
    shutil.copy2(path, backup)
    fd, staged = tempfile.mkstemp(dir=os.path.dirname(path), prefix="providers.", suffix=".toml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    shutil.copymode(path, staged)
    os.replace(staged, path)
    print("%s: pin moved to %s in %s (%s kept)" % (cli_name, new_version, path, backup))


def main(model, args, env):
    opts = parse_args(args)
    if opts.get("help"):
        print(__doc__.strip())
        return EXIT_OK
    env = installer.installer_env(env)
    if opts["names"]:
        names = []
        try:
            for name in opts["names"]:
                cli_name = model.cli_of(name)
                if cli_name not in names:
                    names.append(cli_name)
        except kinds.KindsError as exc:
            raise AkError(str(exc), EXIT_USAGE)
    else:
        names = [c for c in model.cli_names() if (model.clis[c].get("install") or {}).get("latest")]
        if not names:
            print("nothing to update: no CLI has a vendor discovery channel")
            return EXIT_OK
    results = []
    for cli_name in names:
        if opts["json"]:  # one JSON document on stdout; the install's own prints go to stderr
            with contextlib.redirect_stdout(sys.stderr):
                results.append(update_one(model, cli_name, opts, env))
        else:
            results.append(update_one(model, cli_name, opts, env))
    if opts["json"]:
        doc = {"schema": SCHEMA, "interface": common.INTERFACE, "kit": common.VERSION, "results": results}
        json.dump(doc, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for r in results:
            line = "%-11s %-8s %s" % (r["cli"], r["status"], r["to_version"] or "-")
            if r["resolution"]:
                line += "  (%s)" % r["resolution"]
            if r["note"]:
                line += "  — %s" % r["note"]
            print(line)
        print("ak update done: %d updated, %d current, %d skipped, %d failed" % (
            sum(1 for r in results if r["status"] == "updated"),
            sum(1 for r in results if r["status"] == "current"),
            sum(1 for r in results if r["status"] == "skipped"),
            sum(1 for r in results if r["status"] == "failed")))
    failed = any(r["status"] == "failed" for r in results)
    named_skipped = bool(opts["names"]) and any(r["status"] == "skipped" for r in results)
    return EXIT_NOT_READY if (failed or named_skipped) else EXIT_OK
