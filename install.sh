#!/usr/bin/env bash
# Installer for coding-agents-kit (macOS, Linux, WSL, Git Bash on Windows;
# native Windows PowerShell: install.ps1).
#
#   ./install.sh               install or upgrade into ~/.local/share/agentkit,
#                              create ~/.config/agentkit/env (mode 600) if missing,
#                              add one guarded block to your shell rc
#   ./install.sh --no-rc       the same without touching any shell rc (scripts, CI,
#                              containers); run bin/ak by path or add it to PATH yourself
#   ./install.sh --uninstall   remove the install and the rc block; keeps your env
#                              file and your profiles
#
# Idempotent: rerunning upgrades in place. Never overwrites the env file, never
# touches profiles, never installs a coding-agent CLI (that is `ak install`),
# never uses the network.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${AGENTKIT_HOME:-${HOME}/.local/share/agentkit}"
ENV_FILE="${AGENTKIT_ENV:-${HOME}/.config/agentkit/env}"
RC=1
MODE=install

usage() { sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "${arg}" in
    --no-rc) RC=0 ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown option ${arg}" >&2; usage >&2; exit 2 ;;
  esac
done

# shellcheck source=lib/common.sh
. "${SRC}/lib/common.sh"
if ! PY="$(agentkit_python)"; then
  echo "install.sh: python3 >= 3.9 is required (macOS: xcode-select --install or brew install python; Linux: your python3 package)" >&2
  exit 1
fi

# Components owned by the installer; everything else in DEST (profiles/,
# aliases.sh) belongs to the user and survives upgrades and uninstalls.
COMPONENTS="bin lib skills docs providers.toml LICENSE README.md CREDITS.md CHANGELOG.md"
MARKER="${DEST}/.agentkit-install"

# Components are deleted and replaced below, so DEST must be the kit's own
# directory: one without the marker may hold only what ak itself creates
# there before an install (profiles/, aliases.sh). AGENTKIT_HOME=~/.local
# would otherwise wipe ~/.local/bin and ~/.local/lib.
if [[ -d "${DEST}" && ! -e "${MARKER}" ]]; then
  for entry in "${DEST}"/* "${DEST}"/.[!.]*; do
    [[ -e "${entry}" ]] || continue
    case "${entry##*/}" in
      profiles|aliases.sh|.install.*|.no-rc) ;;
      *) echo "install.sh: refusing to use ${DEST}: it is not a coding-agents-kit install (found ${entry##*/}). Choose an empty or dedicated directory." >&2
         exit 1 ;;
    esac
  done
fi

if [[ "${MODE}" == uninstall ]]; then
  AGENTKIT_HOME="${DEST}" "${PY}" "${SRC}/lib/ak.py" alias rc --remove || true
  if [[ ! -e "${MARKER}" ]]; then
    echo "install.sh: no coding-agents-kit install at ${DEST}; nothing removed" >&2
    exit 1
  fi
  for c in ${COMPONENTS}; do rm -rf "${DEST:?}/${c}"; done
  rm -f "${DEST}/aliases.sh" "${MARKER}" "${DEST}/.no-rc"
  echo "removed coding-agents-kit from ${DEST}"
  echo "kept: ${ENV_FILE} and ${DEST}/profiles (delete them yourself if you want them gone)"
  exit 0
fi

umask 077
mkdir -p "${DEST}"
chmod 700 "${DEST}"
STAGE="$(mktemp -d "${DEST}/.install.XXXXXX")"
trap 'rm -rf "${STAGE}"' EXIT

for c in ${COMPONENTS}; do
  [[ -e "${SRC}/${c}" ]] || continue
  cp -R "${SRC}/${c}" "${STAGE}/${c}"
done
find "${STAGE}" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
chmod -R u=rwX,go=rX "${STAGE}"
chmod 755 "${STAGE}/bin/ak" "${STAGE}/bin/agentkit"

# Swap component by component: a stale file from an older version never survives.
for c in ${COMPONENTS}; do
  [[ -e "${STAGE}/${c}" ]] || continue
  rm -rf "${DEST:?}/${c}"
  mv "${STAGE}/${c}" "${DEST}/${c}"
done

printf 'coding-agents-kit install marker: this directory is managed by install.sh\n' > "${MARKER}"
# --no-rc is remembered: `ak alias` then never edits a shell rc either.
if [[ "${RC}" -eq 0 ]]; then : > "${DEST}/.no-rc"; else rm -f "${DEST}/.no-rc"; fi

# The env file is created once and never overwritten.
if [[ ! -e "${ENV_FILE}" ]]; then
  mkdir -p "$(dirname "${ENV_FILE}")"
  chmod 700 "$(dirname "${ENV_FILE}")"
  cp "${SRC}/lib/env.template" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  ENV_NOTE="created ${ENV_FILE} (mode 600) — fill keys there, never in a chat"
else
  ENV_NOTE="kept ${ENV_FILE}"
fi

if [[ "${RC}" -eq 1 ]]; then
  AGENTKIT_HOME="${DEST}" "${DEST}/bin/ak" alias rc --install
  RC_NOTE="open a new shell (or source your rc) so ak is on PATH"
else
  RC_NOTE="no shell rc touched (--no-rc): run ${DEST}/bin/ak, or add ${DEST}/bin to PATH"
fi

echo "installed coding-agents-kit $("${DEST}/bin/ak" --version | sed 's/^agentkit //') into ${DEST}"
echo "${ENV_NOTE}"
echo "${RC_NOTE}"
echo "next: ak doctor      (and: ak install <cli> for any CLI you do not have yet)"
