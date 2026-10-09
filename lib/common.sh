# shellcheck shell=bash
# Shell half of coding-agents-kit: what must happen in a shell before the
# python core takes over. Sourced by bin/ak (and bin/agentkit).
#
#   agentkit_load_env   sources the env file into this process only, so a
#                       line such as KEY="$(security find-generic-password …)"
#                       works; records the names (never the values) it set
#   agentkit_python     prints a python3 >= 3.9 or fails

agentkit_env_file() {
  printf '%s' "${AGENTKIT_ENV:-${HOME}/.config/agentkit/env}"
}

agentkit_load_env() {
  local env_file before after perms flags
  env_file="$(agentkit_env_file)"
  [[ -f "${env_file}" ]] || return 0
  perms="$(stat -f '%Lp' "${env_file}" 2>/dev/null || stat -c '%a' "${env_file}" 2>/dev/null || echo 600)"
  case "${perms}" in
    600|400|700|500) ;;
    *) printf 'ak: warning: %s is mode %s; it holds keys, run: chmod 600 %s\n' "${env_file}" "${perms}" "${env_file}" >&2 ;;
  esac
  before="$(compgen -e | sort)"
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
  after="$(compgen -e | sort)"
  # Names only: lets the core report which keys came from the file.
  AGENTKIT_ENV_FILE_VARS="$(comm -13 <(printf '%s\n' "${before}") <(printf '%s\n' "${after}") | tr '\n' ' ')"
  export AGENTKIT_ENV_FILE_VARS
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
