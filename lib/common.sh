# shellcheck shell=bash
# Shell half of coding-agents-kit: what must happen in a shell before the
# python core takes over. Sourced by bin/ak (and bin/agentkit).
#
#   agentkit_load_env   sources the env file into this process only, so a
#                       line such as KEY="$(security find-generic-password …)"
#                       works
#   agentkit_python     prints a python3 >= 3.9 or fails

agentkit_env_file() {
  printf '%s' "${AGENTKIT_ENV:-${HOME}/.config/agentkit/env}"
}

agentkit_load_env() {
  local env_file perms flags
  env_file="$(agentkit_env_file)"
  [[ -f "${env_file}" ]] || return 0
  # GNU stat first: on Linux `stat -f` is filesystem status and "succeeds".
  perms="$(stat -c '%a' "${env_file}" 2>/dev/null || stat -f '%Lp' "${env_file}" 2>/dev/null || echo 600)"
  case "${perms}" in
    600|400|700|500) ;;
    *) printf 'ak: warning: %s is mode %s; it holds keys, run: chmod 600 %s\n' "${env_file}" "${perms}" "${env_file}" >&2 ;;
  esac
  # The file is the user's shell code: an unset variable or a failing line
  # in it must not abort the launcher, so -e and -u are off while it runs.
  flags="$-"
  set +eu
  set -a
  # shellcheck disable=SC1090
  . "${env_file}"
  set +a
  [[ "${flags}" == *e* ]] && set -e
  [[ "${flags}" == *u* ]] && set -u
  return 0
}

agentkit_python() {
  local c
  for c in "${AGENTKIT_PYTHON:-}" python3 python; do
    [[ -n "${c}" ]] || continue
    command -v "${c}" >/dev/null 2>&1 || continue
    if "${c}" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
      command -v "${c}"
      return 0
    fi
  done
  return 1
}
