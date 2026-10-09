# shellcheck shell=bash
# A minimal scope the harness scope runs from another directory.

scope_harness_selftest() {
  check "the runner resolves its own root" test -f "${ROOT}/tests/run.sh"
}
