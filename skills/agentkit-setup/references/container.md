# Flow C — container recipes

The helper renders; you place. It prints to stdout and writes nothing unless `--out FILE` is given (a new file, mode 644, never overwriting).

## Inputs you must have

- `--ref`: a release tag such as `v0.3.0`. A branch, `latest` or a short name is refused.
- `--sha256`: the 64 hex characters of `coding-agents-kit-<tag>.tar.gz`, from that release's `SHA256SUMS`. Ask the user, or (with their consent to use the network) download the file and read the line:
  ```bash
  curl -fsSL -o SHA256SUMS https://github.com/DailybotHQ/coding-agents-kit/releases/download/v0.3.0/SHA256SUMS
  grep coding-agents-kit-v0.3.0.tar.gz SHA256SUMS
  ```
  Never invent a digest and never skip it.

## Formats

```bash
# test: container
python3 coding-agents-kit/lib/ak.py setup docker --ref v0.3.0 --sha256 8c163a81fa31151cd577797f07cfbe3e61dad49ff691de0b6d5de0975f1cc8ca --format compose
python3 coding-agents-kit/lib/ak.py setup docker --ref v0.3.0 --sha256 8c163a81fa31151cd577797f07cfbe3e61dad49ff691de0b6d5de0975f1cc8ca --format entrypoint
```

- `dockerfile` (default): base pinned by tag, the tarball downloaded to a file, verified with `sha256sum -c` **before** it is unpacked, installed as a non-root user with `--no-rc`, config and profiles as volumes, PATH set, a `HEALTHCHECK` running `ak doctor --json`.
- `compose`: the two volumes, key **names** passed through from the shell or an env_file with no value, an optional read-only root.
- `entrypoint`: exports `AGENTKIT_PERMISSIONS` from `AGENTKIT_POSTURE` (`auto` or `ask`) and runs the command.
- `devcontainer`: a minimal alternative; prefer `dck` (devcontainer-kit), whose images install this kit from the same pinned, verified tarball.

Options: `--base debian|ubuntu`, `--cli claude,codex,...` (installed by `ak install` at build time; npm-installed CLIs need a recent Node — see `dck`), `--user NAME` (non-root).

## Rules the recipe enforces on itself

No fetch piped into a shell; no `latest`; every `FROM` pinned by tag; no `ARG`/`ENV` named like a key or token; a non-root `USER` before the kit is installed; the digest checked before extraction; `--no-rc`; a healthcheck. A recipe that would break one of them is never printed.

## Not supported, said honestly

Alpine and other musl images: the pinned CLI binaries are glibc builds. Use `--base debian` or `ubuntu`.

## Keys at run time

`docker run -e ZAI_CODING_API_KEY` (name only: the value comes from the user's shell), a compose `env_file`, or a secret mounted into `~/.config/agentkit/env` (mode 600). The image never contains a key. `[GATE: repository write]` before writing any file into the user's repository.
