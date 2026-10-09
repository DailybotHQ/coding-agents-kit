# shellcheck shell=bash
# Helpers shared by every scope in tests/scopes/. Sourced by tests/run.sh,
# which defines ROOT, TESTS, FAKES, SANDBOX, BASE_PATH and pass/fail/skip.
#
# A "box" is one isolated world for a group of checks:
#   $BOX/home   the HOME every command sees
#   $BOX/bin    the fakes visible on PATH (all seven unless removed)
#   $BOX/work   a working directory
# Commands run under `env -i`: nothing from the developer's environment
# (real keys, real CLI homes, real PATH) can reach the kit or a fake.

ALL_CLIS="claude codex agent opencode pi cline grok"

# box_new <name> [cli...] — a fresh box; the named fakes (default: all).
box_new() {
  BOX="${SANDBOX}/$1"
  shift
  rm -rf "${BOX}"
  mkdir -p "${BOX}/home" "${BOX}/bin" "${BOX}/work" "${BOX}/tmp"
  cp "${FAKES}/_fake.sh" "${BOX}/bin/"
  local c
  local -a clis=("$@")
  # shellcheck disable=SC2206  # ALL_CLIS is a fixed word list
  [[ ${#clis[@]} -gt 0 ]] || clis=(${ALL_CLIS})
  for c in "${clis[@]}"; do
    cp "${FAKES}/${c}" "${BOX}/bin/${c}"
  done
}

# box_env_file <line...> — the box's kit env file (mode 600).
box_env_file() {
  mkdir -p "${BOX}/home/.config/agentkit"
  printf '%s\n' "$@" > "${BOX}/home/.config/agentkit/env"
  chmod 600 "${BOX}/home/.config/agentkit/env"
}

# box_run [VAR=value...] -- <command...> — runs a command inside the box
# (cwd $BOX/work unless BOX_CWD is set), stdin closed, stdout+stderr merged.
box_run() {
  local -a envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  [[ "${1:-}" == "--" ]] && shift
  ( cd "${BOX_CWD:-${BOX}/work}" && env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" \
      TMPDIR="${BOX}/tmp" ${envs[@]+"${envs[@]}"} "$@" </dev/null 2>&1 )
}

# ak [VAR=value...] -- <ak args...> — runs bin/ak in the box (merged output).
ak() {
  local -a envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  [[ "${1:-}" == "--" ]] && shift
  box_run ${envs[@]+"${envs[@]}"} -- bash "${ROOT}/bin/ak" "$@"
}

# ak_split [VAR=value...] -- <ak args...> — stdout to $BOX/out, stderr to
# $BOX/err; returns the exit status.
ak_split() {
  local -a envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  [[ "${1:-}" == "--" ]] && shift
  ( cd "${BOX_CWD:-${BOX}/work}" && env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" \
      TMPDIR="${BOX}/tmp" ${envs[@]+"${envs[@]}"} bash "${ROOT}/bin/ak" "$@" \
      </dev/null >"${BOX}/out" 2>"${BOX}/err" )
}

# The ARG= lines of a fake's record, joined by "|" (exact argv, boundaries kept).
argv_of() {
  printf '%s\n' "$1" | sed -n 's/^ARG=//p' | paste -sd '|' -
}

# check <name> <command...> — pass when the command succeeds (output hidden).
check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then pass "${name}"; else fail "${name}"; fi
}

# expect_eq <name> <got> <want>
expect_eq() {
  if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1: got '$2', want '$3'"; fi
}

# expect_line <name> <text> <exact line>
expect_line() {
  if printf '%s\n' "$2" | grep -qxF -- "$3"; then pass "$1"; else fail "$1: no line '$3' in: $(printf '%s' "$2" | tr '\n' ' ' | cut -c1-400)"; fi
}

# expect_has <name> <text> <substring>
expect_has() {
  if [[ "$2" == *"$3"* ]]; then pass "$1"; else fail "$1: '$3' not in: $(printf '%s' "$2" | tr '\n' ' ' | cut -c1-400)"; fi
}

# expect_lacks <name> <text> <substring>
expect_lacks() {
  if [[ "$2" != *"$3"* ]]; then pass "$1"; else fail "$1: unexpected '$3' in output"; fi
}

# file_mode <path> — octal permission bits (BSD and GNU stat).
file_mode() {
  stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"
}

# json_get <file|-> <python expression over `d`> — prints the value.
json_get() {
  local src="$1" expr="$2"
  "${AK_PY}" - "${src}" "${expr}" <<'PY'
import json, sys
src, expr = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin if src == "-" else open(src))
v = eval(expr, {"d": d})
print(json.dumps(v) if not isinstance(v, str) else v)
PY
}

# py_checks <tests/py/script.py> [args...] — runs a python check script
# (with the interpreter under test) and folds its `ok …` / `FAIL …` lines
# into the counters. A crash is a failure, with its last line.
py_checks() {
  local script="$1" out line status
  shift
  out="$(cd "${SANDBOX}" && env -i HOME="${HOME}" PATH="${BASE_PATH}" "${AK_PY}" "${ROOT}/tests/py/${script}" "$@" 2>&1)"
  status=$?
  while IFS= read -r line; do
    case "${line}" in
      "ok "*) pass "${line#ok }" ;;
      "FAIL "*) fail "${line#FAIL }" ;;
    esac
  done <<<"${out}"
  if [[ "${status}" -ne 0 ]]; then
    fail "${script} crashed (exit ${status}): $(printf '%s\n' "${out}" | tail -1)"
  fi
}
