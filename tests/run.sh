#!/usr/bin/env bash
# Validation gate for coding-agents-kit.
#
# Everything runs against a throwaway HOME under $TMPDIR: the suite never
# reads or writes the real ~/.config, ~/.local, ~/.claude, ~/.codex or your
# shell rc, never installs a CLI and never touches the network. Every agent
# CLI is a fake from tests/fakes/ that records its argv and environment.
#
# Usage: tests/run.sh [scope...]      (no scope = every scope except live)
# Output: one `ok   <check>` / `FAIL <check>` / `skip <check>` line per check,
# then a final `passed: N  failed: N  skipped: N` line. Exit 0 only when
# nothing failed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS="${ROOT}/tests"
FAKES="${TESTS}/fakes"

# Order matters only for readability of the report.
ALL_SCOPES="harness lint kinds dispatch profiles permissions doctor run install aliases skill hooks security"
KNOWN_SCOPES="${ALL_SCOPES} live harness-selftest"

PASSES=0
FAILS=0
SKIPS=0

pass() { PASSES=$((PASSES + 1)); printf 'ok   %s\n' "$1"; }
fail() { FAILS=$((FAILS + 1)); printf 'FAIL %s\n' "$1"; }
skip() { SKIPS=$((SKIPS + 1)); printf 'skip %s\n' "$1"; }

usage() {
  printf 'usage: tests/run.sh [scope...]\nscopes: %s\n' "${KNOWN_SCOPES}" >&2
}

# The interpreter under test. AK_TEST_PYTHON lets CI (and a developer) run
# the whole suite on an older python3, e.g. AK_TEST_PYTHON=/usr/bin/python3.
AK_PY="${AK_TEST_PYTHON:-$(command -v python3 || true)}"
if [[ -z "${AK_PY}" ]] || ! "${AK_PY}" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  echo "tests/run.sh: needs python3 >= 3.9 (set AK_TEST_PYTHON to choose one)" >&2
  exit 2
fi

REAL_HOME="${HOME}"
REAL_PATH="${PATH}"  # used by the opt-in live scope
export REAL_PATH
SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/agentkit-tests.XXXXXX")"
SANDBOX="$(cd "${SANDBOX}" && pwd -P)"
trap 'rm -rf "${SANDBOX}"' EXIT

# A tiny system bin: python3 (the one under test) and nothing else that could
# shadow a fake. Homebrew and ~/.local/bin are never on the suite's PATH, so a
# real claude/codex/pi/cline can never answer in place of a fake.
SYSBIN="${SANDBOX}/sysbin"
mkdir -p "${SYSBIN}"
ln -s "${AK_PY}" "${SYSBIN}/python3"
BASE_PATH="${SYSBIN}:/usr/bin:/bin:/usr/sbin:/sbin"

# Proof that the real HOME is never touched: the kit's own paths must not
# appear during the run (checked again at the end).
real_home_marks() {
  local p
  for p in "${REAL_HOME}/.local/share/agentkit" "${REAL_HOME}/.config/agentkit"; do
    [[ -e "${p}" ]] && printf '%s\n' "${p}"
  done
  for p in .zshrc .bashrc .bash_profile .profile; do
    [[ -f "${REAL_HOME}/${p}" ]] && grep -q '>>> agentkit' "${REAL_HOME}/${p}" && printf '%s\n' "${REAL_HOME}/${p}"
  done
  return 0
}
REAL_HOME_BEFORE="$(real_home_marks)"

# Everything below runs with the sandbox as HOME, even helper commands.
export HOME="${SANDBOX}/home"
mkdir -p "${HOME}"
unset AGENTKIT_HOME AGENTKIT_ENV AGENTKIT_PROFILE AGENTKIT_PROFILES_DIR AGENTKIT_PERMISSIONS

# shellcheck source=tests/lib.sh
. "${TESTS}/lib.sh"

run_scope() {
  local scope="$1" file="${TESTS}/scopes/$1.sh"
  echo "## ${scope}"
  if [[ ! -f "${file}" ]]; then
    # A scope named on the command line must exist: a gate that names it can
    # never pass vacuously. The full run only notes what is still missing.
    if [[ "${EXPLICIT}" -eq 1 ]]; then fail "${scope}: scope not implemented"; else skip "${scope}: scope not implemented yet"; fi
    return 0
  fi
  # shellcheck source=/dev/null
  . "${file}"
  "scope_${scope//-/_}"
}

scopes=()
EXPLICIT=0
if [[ $# -eq 0 || "${1:-}" == all ]]; then
  for s in ${ALL_SCOPES}; do scopes+=("${s}"); done
else
  EXPLICIT=1
  for s in "$@"; do
    case " ${KNOWN_SCOPES} " in
      *" ${s} "*) scopes+=("${s}") ;;
      *) echo "tests/run.sh: unknown scope '${s}'" >&2; usage; exit 2 ;;
    esac
  done
fi

for s in "${scopes[@]}"; do
  run_scope "${s}"
done

echo "## guard"
if [[ "$(real_home_marks)" == "${REAL_HOME_BEFORE}" ]]; then
  pass "the real HOME gained no agentkit path or rc block"
else
  fail "the real HOME changed during the run: $(real_home_marks | tr '\n' ' ')"
fi

echo ""
echo "passed: ${PASSES}  failed: ${FAILS}  skipped: ${SKIPS}"
[[ "${FAILS}" -eq 0 ]]
