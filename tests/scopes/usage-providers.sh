# shellcheck shell=bash
# `ak usage` sources, one adapter at a time, against a loopback fake endpoint
# (tests/py/fake_usage_server.py): bash-free checks for every adapter, plus the
# real launcher end to end in a sandbox home.

# usage_server_start <routes.json> — starts the fake endpoint; sets USAGE_PORT
# and USAGE_PID. The routes file is re-read on every request.
usage_server_start() {
  local routes="$1" portfile="${BOX}/port"
  rm -f "${portfile}"
  "${AK_PY}" "${ROOT}/tests/py/fake_usage_server.py" --routes "${routes}" --port-file "${portfile}" --log "${BOX}/server.log" \
    >/dev/null 2>&1 &
  USAGE_PID=$!
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    [[ -s "${portfile}" ]] && break
    sleep 0.25
  done
  USAGE_PORT="$(cat "${portfile}" 2>/dev/null)"
}

usage_server_stop() {
  [[ -n "${USAGE_PID:-}" ]] && kill "${USAGE_PID}" 2>/dev/null
  wait "${USAGE_PID:-0}" 2>/dev/null
  USAGE_PID=""
}

scope_usage_providers() {
  check "usage providers: the fake endpoint server imports" "${AK_PY}" -c 'import sys; sys.path.insert(0, sys.argv[1]); import fake_usage_server' "${ROOT}/tests/py"

  # Every adapter against the REAL providers.toml, bash free.
  py_checks usage_provider_checks.py

  # The launcher end to end: a Claude login in a box, one request to the fake.
  local doc status
  box_new usage-providers claude
  mkdir -p "${BOX}/home/.claude"
  printf '%s' '{"claudeAiOauth":{"accessToken":"planted-claude-cli-0x1","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' \
    > "${BOX}/home/.claude/.credentials.json"
  printf '%s' '{"/claude":{"json":{"five_hour":{"utilization":42,"resets_at":"2099-01-01T00:00:00Z"},"seven_day":{"utilization":13,"resets_at":"2099-01-02T00:00:00Z"}}}}' \
    > "${BOX}/routes.json"
  usage_server_start "${BOX}/routes.json"
  doc="${BOX}/usage.json"
  ak_split AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH="http://127.0.0.1:${USAGE_PORT}/claude" -- usage claude --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "usage claude cli: exit 0 for a healthy Claude account" "${status}" 0
  expect_eq "usage claude cli: the 5-hour window is reported" \
    "$(json_get "${doc}" '[w["used_pct"] for w in d["rows"][0]["windows"]]')" '[42, 13]'
  expect_eq "usage claude cli: the plan comes from the login" "$(json_get "${doc}" 'd["rows"][0]["plan"]')" "max"
  expect_lacks "usage claude cli: the token is not in the output" "$(cat "${BOX}/out" "${BOX}/err")" "planted-claude-cli-0x1"
  expect_eq "usage claude cli: the fake endpoint saw exactly one request" "$(wc -l < "${BOX}/server.log" | tr -d ' ')" 1
  usage_server_stop
}
