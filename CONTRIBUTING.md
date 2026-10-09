# Contributing to coding-agents-kit

Thanks for helping. This repository is small on purpose: a bash launcher, a
python3 standard-library core and data in `providers.toml`. Coding agents
working here should start with [AGENTS.md](AGENTS.md).

## Development setup

- bash, python3 ≥ 3.9 (standard library only — do not add dependencies),
  git, and [shellcheck](https://www.shellcheck.net) for the lint gate.
- Clone and run from the checkout: `bin/ak --version`. **Do not install
  into your real home while developing**; the test suite never does.

## The gate

```bash
bash tests/run.sh                    # everything (sandbox HOME, fake CLIs, no network)
bash tests/run.sh dispatch profiles  # only the scopes your change touches
bash scripts/check-public-hygiene.sh # no private context or secret-shaped strings
```

[docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) maps each source file to its
scope. CI runs the full suite on ubuntu, macOS and python 3.9, the Windows
layer, and the public-hygiene check; all must be green to merge.

Adding a kind is a data entry in `providers.toml` plus a test — see
[docs/kinds.md](docs/kinds.md#adding-a-kind).

## Rules that keep the kit safe

- Never print, log or write the value of a `*_API_KEY` / `*_TOKEN`; refer to
  variables by name. Test fixtures that look like secrets must be visibly
  fake (`fake`, `test`, `planted`, `example`) and listed in
  `.public-hygiene-allow` with a reason.
- Autonomy flags live only in `providers.toml`'s `auto` field. `ak` applies
  them by default, and the opt-out (`--ask`, `AGENTKIT_PERMISSIONS=ask`) must
  suppress them on every launch path: interactive, `ak run`, profiles,
  presets, aliases and nested launches.
- No fetch-piped-to-shell lines; pin every external tool and action by
  version (actions by commit SHA).
- No private context in a public repository: no personal paths, internal
  names or non-public addresses (the hygiene check enforces the list).

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org):
  `feat(run): …`, `fix(profiles): …`, `docs: …`, `test: …`, `ci: …`,
  `chore: …`; `!` (or a `BREAKING CHANGE:` footer) for a breaking change.
- Work on a branch and open a pull request against `main`; fill in the
  template (summary, linked issue, test evidence, checklist). `main` is
  protected: CI must pass and one maintainer review is required.
- A change to interface 1 (`ak doctor --json`, `ak env`, `ak run`) is a
  breaking change: it bumps the interface version and the minor version
  while the kit is `0.x`.
- No DCO or CLA is required; by contributing you agree your work is
  released under the [MIT License](LICENSE).

## Releases (maintainers)

1. Update `VERSION` in `lib/common.py` and every place `lint` checks
   (skill, README, docs, schema), and add the `CHANGELOG.md` section.
2. Merge to `main` with CI green.
3. Push an **annotated** tag: `git tag -a vX.Y.Z -m "coding-agents-kit vX.Y.Z" && git push origin vX.Y.Z`.
   The [release workflow](.github/workflows/release.yml) checks the tag
   against the version, runs the suite, and publishes the GitHub release with
   the CHANGELOG section as notes, the source tarball and `SHA256SUMS`
   (a `-beta.N`/`-rc.N` suffix makes it a pre-release).

## Reporting a vulnerability

Never in a public issue — see [SECURITY.md](SECURITY.md).
