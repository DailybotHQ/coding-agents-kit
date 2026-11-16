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

  # --- advisory token sums: observed samples only, absence is unknown ------
  mkdir -p "${BOX}/home/.local/state/agentkit/token-samples/claude@default"
  printf '{"cli":"claude","profile":"@default","tokens":{"input":40,"output":20,"cache_read":0,"cache_write":10,"total":70},"recorded_at":1}\n' > "${BOX}/home/.local/state/agentkit/token-samples/claude@default/sample-1.json"
  printf '{"cli":"claude","profile":"@default","tokens":{"input":60,"output":30,"cache_read":20,"cache_write":0,"total":110},"recorded_at":2}\n' > "${BOX}/home/.local/state/agentkit/token-samples/claude@default/sample-2.json"
  ak_split -- usage --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "usage advisory: json still matches the schema with advisory rows" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")" "valid"
  expect_eq "usage advisory: the sampled account carries its observed sums" \
    "$(json_get "${doc}" '[[r["advisory"]["runs"], r["advisory"]["tokens"]["input"], r["advisory"]["tokens"]["total"]] for r in d["rows"] if r["cli"] == "claude" and r["profile"] == "@default"]')"     '[[2, 100, 180]]'
  expect_eq "usage advisory: accounts with no samples carry no advisory key" \
    "$(json_get "${doc}" '[r.get("advisory", "absent") for r in d["rows"] if r["cli"] == "codex"]')" \
    '["absent"]'
  expect_eq "usage advisory: an explicit zero is a report (coverage counts it)" \
    "$(json_get "${doc}" '[[r["advisory"]["tokens"]["cache_read"], r["advisory"]["coverage"]["cache_read"]] for r in d["rows"] if r["cli"] == "claude" and r["profile"] == "@default"]')" '[[20, 2]]'
  # Runs that report no total (claude publishes none) leave the total null —
  # never zero, never the sum of the components; a corrupt sample and a
  # staged .tmp- file are not counted.
  local sd="${BOX}/home/.local/state/agentkit/token-samples/claude@default"
  rm -f "${sd}"/sample-*.json
  printf '{"cli":"claude","profile":"@default","tokens":{"input":17,"output":5,"cache_read":null,"cache_write":null,"total":null},"recorded_at":3}\n' > "${sd}/sample-3.json"
  printf '{"cli":"claude","profile":"@default","tokens":{"input":3,"output":null,"cache_read":null,"cache_write":null,"total":null},"recorded_at":4}\n' > "${sd}/sample-4.json"
  printf '{"cli":"claude","prof' > "${sd}/sample-5.json"
  printf '{"cli":"claude","profile":"@default","tokens":{"input":1000,"output":1000,"cache_read":null,"cache_write":null,"total":2000},"recorded_at":6}\n' > "${sd}/.tmp-staged.json"
  printf '{"cli":"claude","profile":"@work","tokens":{"input":1000,"output":null,"cache_read":null,"cache_write":null,"total":null},"recorded_at":7}\n' > "${sd}/sample-7.json"
  ak_split -- usage --json
  cp "${BOX}/out" "${doc}"
  expect_eq "usage advisory: still matches the schema with null sums" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")" "valid"
  expect_eq "usage advisory: an unreported total stays null; partial coverage is visible" \
    "$(json_get "${doc}" '[[r["advisory"]["runs"], r["advisory"]["tokens"], r["advisory"]["coverage"]] for r in d["rows"] if r["cli"] == "claude" and r["profile"] == "@default"]')" \
    '[[2, {"cache_read": null, "cache_write": null, "input": 20, "output": 5, "total": null}, {"cache_read": 0, "cache_write": 0, "input": 2, "output": 1, "total": 0}]]'
  rm -rf "${BOX}/home/.local/state/agentkit/token-samples"

  # The writer: two runs in the same second from the same process keep two
  # samples (unique names, no replacement), private files, nothing recorded
  # for a run that reported nothing, and an explicit zero kept as zero.
  check "usage advisory: tokens_add keeps every sample, 0600, zero kept, nothing for nothing" \
    box_run -- "${AK_PY}" -c '
import os, stat, sys
sys.path.insert(0, sys.argv[1] + "/lib"); import state
env = dict(os.environ)
t = {"input": 4, "output": 0, "cache_read": None, "cache_write": None, "total": None}
assert state.tokens_add(env, "claude", "@w", t, 100) and state.tokens_add(env, "claude", "@w", t, 100)
assert not state.tokens_add(env, "claude", "@w", dict.fromkeys(t), 100)
d = state._tokens_dir(env, "claude", "@w")
names = os.listdir(d)
assert len(names) == 2 and all(n.startswith("sample-") for n in names), names
assert all(stat.S_IMODE(os.stat(os.path.join(d, n)).st_mode) == 0o600 for n in names)
assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
g = state.tokens_get(env, "claude", "@w")
assert g["runs"] == 2 and g["tokens"]["input"] == 8 and g["tokens"]["output"] == 0 and g["tokens"]["total"] is None, g
assert g["coverage"]["output"] == 2 and g["coverage"]["total"] == 0, g
' "${ROOT}"

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
