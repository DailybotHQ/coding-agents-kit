# shellcheck shell=bash
# `ak pick` (lib/pick.py): the selection policy is exercised bash free by
# tests/py/pick_checks.py (Windows CI runs it natively); here `ak pick` runs
# through the real launcher in a sandbox home against the loopback fake usage
# endpoint, with several Claude accounts whose numbers differ.

scope_pick() {
  py_checks pick_checks.py

  local doc status out before after schema="${ROOT}/docs/schema/pick-v1.json"
  box_new pick claude
  local t0="planted-pick-default-0x1" t1="planted-pick-work-0x1" t2="planted-pick-two-0x1" name tok dir
  for name in default work 2; do
    case "${name}" in default) tok="${t0}"; dir="${BOX}/home/.claude" ;; work) tok="${t1}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/work" ;;
      2) tok="${t2}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/2" ;; esac
    mkdir -p "${dir}"
    printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${tok}" > "${dir}/.credentials.json"
  done
  "${AK_PY}" - "${BOX}/routes.json" "${t0}" "${t1}" "${t2}" <<'PY'
import json, sys
path, t0, t1, t2 = sys.argv[1:]
def c(a, b):
    return {"json": {"five_hour": {"utilization": a, "resets_at": "2099-01-01T00:00:00Z"}, "seven_day": {"utilization": b, "resets_at": "2099-01-05T00:00:00Z"}}}
json.dump({"/claude": {"by_bearer": {t0: c(10, 85), t1: c(55, 20), t2: c(91, 30)}}}, open(path, "w"))
PY
  usage_server_start "${BOX}/routes.json"
  local url="AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://127.0.0.1:${USAGE_PORT}/claude"
  before="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"

  # default: 5h 90 free, 7d 90-85 = 5 -> 5 · work: 45, 70 -> 45 · 2: 9, 60 -> 9
  ak_split "${url}" -- pick claude; status=$?
  expect_eq "pick cli: exit 0 when an account qualifies" "${status}" 0
  expect_has "pick cli: the account with the most headroom is chosen (@work, 45%)" "$(cat "${BOX}/out")" "claude @work  headroom 45%"

  doc="${BOX}/pick.json"
  ak_split "${url}" -- pick claude --count 3 --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "pick cli: --count 3 --json exits 0" "${status}" 0
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")"
  expect_eq "pick json: ak pick --json matches docs/schema/pick-v1.json" "${out}" "valid"
  expect_eq "pick json: accounts ranked by headroom" "$(json_get "${doc}" '[c["profile"] for c in d["chosen"]]')" '["@work", "@2", "@default"]'
  expect_eq "pick json: schema and interface" "$(json_get "${doc}" '[d["schema"], d["interface"]]')" '["pick-v1", 1]'

  ak_split "${url}" -- pick claude --exclude @work; status=$?
  expect_has "pick cli: --exclude leaves a busy account out" "$(cat "${BOX}/out")" "claude @2"

  ak_split "${url}" -- pick claude --need 5h:95; status=$?
  expect_eq "pick cli: none qualifies exits 1" "${status}" 1
  expect_has "pick cli: the refusal names the soonest reset" "$(cat "${BOX}/err")" "Soonest reset"

  ak_split "${url}" -- pick claude @nobody; status=$?
  expect_eq "pick cli: nothing matches exits 3" "${status}" 3
  ak_split -- pick nope; status=$?
  expect_eq "pick cli: an unknown kind exits 2" "${status}" 2
  ak_split -- pick; status=$?
  expect_eq "pick cli: a missing kind exits 2" "${status}" 2
  ak_split -- pick claude --bogus; status=$?
  expect_eq "pick cli: an unknown option exits 2" "${status}" 2
  out="$(ak -- pick --help)"; status=$?
  expect_eq "pick cli: --help exits 0" "${status}" 0
  expect_has "pick cli: --help prints the grammar" "${out}" "ak pick <kind-or-cli>"
  out="$(ak -- --help)"
  expect_has "pick cli: ak --help lists the command" "${out}" "ak pick"

  # Secrecy and read-only: no token in any output; nothing written under the home.
  ak_split "${url}" -- pick claude --count 3 --json
  expect_lacks "pick security: no token in stdout or stderr" "$(cat "${BOX}/out" "${BOX}/err")" "planted-pick"
  after="$(find "${BOX}/home" -type f ! -path "*/.local/state/agentkit/usage-cache/*" | sort | xargs -r cksum)"
  expect_eq "pick security: ak pick writes nothing under the home but its usage cache" "${before}" "${after}"
  usage_server_stop

  out="$(ak AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://example.com/x -- pick claude --max-age 0)"; status=$?
  expect_eq "pick security: a non-loopback URL override is never fetched (exit 1 or 2)" "$([[ ${status} -eq 1 || ${status} -eq 2 ]] && echo ok)" ok

  check "pick platform: lib/pick.py imports nothing POSIX-only and calls no fork/alarm/getuid" \
    bash -c '! grep -Eq "import (fcntl|pwd|grp|termios|resource)|os\.fork|signal\.alarm|os\.getuid" "$1"' _ "${ROOT}/lib/pick.py"
  check "pick platform: CI runs pick_checks.py natively on Windows" \
    bash -c 'grep -q "pick_checks.py" "$1"' _ "${ROOT}/.github/workflows/ci.yml"
}
