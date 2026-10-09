# shellcheck shell=bash
# The kinds model: providers.toml, the loader, templates and config writers.

scope_kinds() {
  local scratch="${SANDBOX}/kinds"
  rm -rf "${scratch}"
  mkdir -p "${scratch}"
  py_checks kinds_checks.py "${ROOT}" "${scratch}"
  check "kinds.py check accepts the shipped providers.toml" "${AK_PY}" "${ROOT}/lib/kinds.py" check
}
