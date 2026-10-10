# shellcheck shell=bash
# `ak setup` (lib/setup.py): the read-only helpers of the agentkit-setup skill.
# The logic is exercised by tests/py/setup_checks.py (bash free, so Windows CI
# runs it natively); here `ak setup` runs through the real launcher and from an
# uninstalled clone, in a sandbox home.

scope_setup() {
  local out status doc schema="${ROOT}/docs/schema/setup-probe-v1.json" before after planted="planted-setup-key-0x1"

  # Simulated Linux, macOS, Windows, WSL, musl and container hosts; secrecy;
  # read-only; the uninstalled clone; the portability rule.
  py_checks setup_checks.py

  box_new setup
  box_env_file "ZAI_CODING_API_KEY=${planted}"
  doc="${BOX}/probe.json"
  before="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  ak_split -- setup probe --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "setup probe: ak setup probe --json exits 0 through the launcher" "${status}" 0
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")"
  expect_eq "setup probe: the launcher's JSON matches docs/schema/setup-probe-v1.json" "${out}" "valid"
  expect_eq "setup probe: schema and interface" "$(json_get "${doc}" '[d["schema"], d["interface"]]')" '["setup-probe-v1", 1]'
  expect_eq "setup probe: the key is reported by name only" "$(json_get "${doc}" 'd["env_file"]["keys"]')" '["ZAI_CODING_API_KEY"]'
  expect_lacks "setup probe: no key value in the JSON" "$(cat "${doc}")" "${planted}"
  out="$(ak -- setup probe)"; status=$?
  expect_eq "setup probe: the text form exits 0" "${status}" 0
  expect_has "setup probe: the text form names the sections" "${out}" "posture:"
  expect_lacks "setup probe: no key value in the text" "${out}" "${planted}"
  after="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  expect_eq "setup probe: the box's home is byte-identical after probing" "${before}" "${after}"

  out="$(ak -- setup probe --bogus)"; status=$?
  expect_eq "setup probe: an unknown option exits 2" "${status}" 2
  out="$(ak -- setup)"; status=$?
  expect_eq "setup probe: no subcommand exits 2 and prints the grammar" "${status}:$([[ ${out} == *"ak setup probe"* ]] && echo grammar)" "2:grammar"
  out="$(ak -- --help)"
  expect_has "setup probe: ak --help lists the command" "${out}" "ak setup probe"

  # From an uninstalled clone, the way the skill looks at a machine first: the
  # python core runs by path and writes nothing into HOME.
  box_new setup-clone
  out="$(box_run -- "${AK_PY}" "${ROOT}/lib/ak.py" setup probe --json)"; status=$?
  expect_eq "setup probe: it runs from an uninstalled clone" "${status}" 0
  expect_has "setup probe: ... and reports no install" "${out}" '"found": false'
  expect_eq "setup probe: ... leaving the home empty" "$(find "${BOX}/home" -mindepth 1 | wc -l | tr -d ' ')" 0

  # Portability: the shared code path has no POSIX-only primitive.
  check "setup platform: lib/setup.py imports nothing POSIX-only and calls no fork/alarm/getuid" \
    bash -c '! grep -Eq "import (fcntl|pwd|grp|termios|resource)|os\.fork|signal\.alarm|os\.getuid" "$1"' _ "${ROOT}/lib/setup.py"
}
