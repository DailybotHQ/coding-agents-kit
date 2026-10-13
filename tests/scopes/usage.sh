# shellcheck shell=bash
# `ak usage` (lib/usage.py): the pipeline, rendering, --json and the command
# seam. The pipeline itself is exercised by tests/py/usage_checks.py (bash
# free, so Windows CI runs it natively); here `ak usage` runs through the real
# launcher in a sandbox home.

scope_usage() {
  local out status schema="${ROOT}/docs/schema/usage-v1.json" doc

  # The bash-free checks: pipeline, enumeration, deduplication, filters, exit
  # codes, rendering, secrecy, read-only, against a loopback fake endpoint.
  py_checks usage_checks.py

  # The command through bin/ak in a box: a fresh machine with the fake CLIs.
  box_new usage
  doc="${BOX}/usage.json"
  ak_split -- usage --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "usage core: a fresh box has rows that need attention (exit 1)" "${status}" 1
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")"
  expect_eq "usage json: ak usage --json matches docs/schema/usage-v1.json" "${out}" "valid"
  expect_eq "usage json: schema and interface" "$(json_get "${doc}" '[d["schema"], d["interface"]]')" '["usage-v1", 1]'
  expect_eq "usage core: antigravity is a readable source now (no login in a fresh box, never n/d)" \
    "$(json_get "${doc}" '[r["status"] for r in d["rows"] if r["cli"] == "antigravity"]')" '["no_login"]'
  expect_eq "usage core: unsupported sources are listed with a reason, not hidden" \
    "$(json_get "${doc}" 'sorted(r["cli"] for r in d["rows"] if r["status"] == "unsupported")')" '["cline", "cursor", "grok", "opencode", "pi"]'

  out="$(ak -- usage --no-color)"; status=$?
  expect_eq "usage core: the table exits like the JSON" "${status}" 1
  expect_has "usage core: the table has a header" "${out}" "PROFILE"
  expect_has "usage core: unsupported rows print n/d" "${out}" "n/d"

  out="$(ak -- usage nope)"; status=$?
  expect_eq "usage core: an unknown kind exits 2" "${status}" 2
  expect_has "usage core: the error names the kinds" "${out}" "unknown kind"
  out="$(ak -- usage --bogus)"; status=$?
  expect_eq "usage core: an unknown option exits 2" "${status}" 2
  out="$(ak -- usage --help)"; status=$?
  expect_eq "usage core: --help exits 0" "${status}" 0
  expect_has "usage core: --help prints the grammar" "${out}" "ak usage [<kind-or-cli>]"

  out="$(ak -- --help)"
  expect_has "usage core: ak --help lists the command" "${out}" "ak usage"
  expect_has "usage core: ak --help names the status alias" "${out}" "(alias: ak status)"
  out="$(ak -- status --help)"; status=$?
  expect_eq "usage core: ak status is ak usage (--help exits 0)" "${status}" 0
  expect_has "usage core: ak status prints the usage grammar" "${out}" "ak usage [<kind-or-cli>]"

  # An override that leaves the machine is refused before any request.
  out="$(ak AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://example.com/x -- usage claude)"; status=$?
  expect_eq "usage core: a non-loopback URL override is refused or unused (never fetched)" "$([[ ${status} -eq 1 || ${status} -eq 2 ]] && echo ok)" ok

  # Portability: the shared code path has no POSIX-only primitive (the same
  # rule the plan's gate repeats); Windows runs the python core natively.
  check "usage platform: lib/usage.py imports nothing POSIX-only and calls no fork/alarm/getuid" \
    bash -c '! grep -Eq "import (fcntl|pwd|grp|termios|resource)|os\.fork|signal\.alarm|os\.getuid" "$1"' _ "${ROOT}/lib/usage.py"
  check "usage platform: lib/usage.py hardcodes no /home or C:\\ path" \
    bash -c '! grep -Eq "(/home/|C:[\\])" "$1"' _ "${ROOT}/lib/usage.py"
  check "usage platform: CI runs the bash-free checks natively on Windows" \
    bash -c 'grep -q "usage_checks.py" "$1" && grep -q "usage_provider_checks.py" "$1"' _ "${ROOT}/.github/workflows/ci.yml"

  # The real HOME-equivalent stays untouched: a run writes nothing in the box.
  local before after
  before="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  ak_split -- usage >/dev/null
  after="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  expect_eq "usage core: ak usage writes nothing under the home" "${before}" "${after}"
}
