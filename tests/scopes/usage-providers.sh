# shellcheck shell=bash
# `ak usage` sources, one adapter at a time, against a loopback fake endpoint
# (tests/py/fake_usage_server.py). Checks are added with each adapter.

scope_usage_providers() {
  check "usage providers: the fake endpoint server imports" "${AK_PY}" -c 'import sys; sys.path.insert(0, sys.argv[1]); import fake_usage_server' "${ROOT}/tests/py"
}
