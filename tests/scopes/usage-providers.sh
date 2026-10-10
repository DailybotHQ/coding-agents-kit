# shellcheck shell=bash
# `ak usage` sources, one adapter at a time, against a loopback fake endpoint
# (tests/py/fake_usage_server.py): bash-free checks for every adapter, plus the
# real launcher end to end in a sandbox home.

scope_usage_providers() {
  check "usage providers: the fake endpoint server imports" "${AK_PY}" -c 'import sys; sys.path.insert(0, sys.argv[1]); import fake_usage_server' "${ROOT}/tests/py"

  # Every adapter against the REAL providers.toml, bash free.
  py_checks usage_provider_checks.py

  # The launcher end to end: a Claude login in a box, one request to the fake.
  local doc status before after out
  box_new usage-providers claude
  mkdir -p "${BOX}/home/.claude"
  local planted="planted-claude-cli-0x1"
  printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${planted}" \
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
  expect_lacks "usage claude cli: the token is not in the output" "$(cat "${BOX}/out" "${BOX}/err")" "${planted}"
  expect_eq "usage claude cli: the fake endpoint saw exactly one request" "$(wc -l < "${BOX}/server.log" | tr -d ' ')" 1
  usage_server_stop

  # The developer's layout through the real launcher: several Claude accounts
  # (default, @work, @2) plus Z.AI keys, Cursor and Grok present. Each account
  # has its own recognisable numbers; a mix-up would show.
  box_new usage-scenario claude agent grok
  local t0="planted-scn-default-0x1" t1="planted-scn-work-0x1" t2="planted-scn-two-0x1" z0="planted-scn-zai-0x1" z2="planted-scn-zai-0x2"
  local name tok dir
  for name in default work 2; do
    case "${name}" in default) tok="${t0}"; dir="${BOX}/home/.claude" ;; work) tok="${t1}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/work" ;;
      2) tok="${t2}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/2" ;; esac
    mkdir -p "${dir}"
    printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${tok}" > "${dir}/.credentials.json"
  done
  box_env_file "ZAI_CODING_API_KEY=${z0}" "ZAI_CODING_API_KEY_2=${z2}"
  "${AK_PY}" - "${BOX}/routes.json" "${t0}" "${t1}" "${t2}" "${z0}" "${z2}" <<'PY'
import json, sys
path, t0, t1, t2, z0, z2 = sys.argv[1:]
def c(a, b):
    return {"json": {"five_hour": {"utilization": a, "resets_at": "2099-01-01T00:00:00Z"}, "seven_day": {"utilization": b, "resets_at": "2099-01-05T00:00:00Z"}}}
def z(p):
    return {"json": {"data": {"planName": "lite", "limits": [{"type": "TOKENS_LIMIT", "percentage": p, "nextResetTime": 4070908800000}]}}}
json.dump({"/claude": {"by_bearer": {t0: c(10, 5), t1: c(55, 20), t2: c(91, 70)}},
           "/zai": {"by_bearer": {z0: z(48), z2: z(77)}}}, open(path, "w"))
PY
  usage_server_start "${BOX}/routes.json"
  before="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  ak_split AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH="http://127.0.0.1:${USAGE_PORT}/claude" \
    AGENTKIT_USAGE_URL_ZAI_QUOTA="http://127.0.0.1:${USAGE_PORT}/zai" -- usage --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "usage scenario cli: a mixed layout is healthy (exit 0)" "${status}" 0
  expect_eq "usage scenario cli: rows in the documented order" \
    "$(json_get "${doc}" '[r["cli"] + r["profile"] for r in d["rows"]]')" \
    '["claude@default", "claude@2", "claude@work", "cursor@default", "grok@default", "zai@default", "zai@2"]'
  expect_eq "usage scenario cli: each Claude account shows its own 5-hour numbers" \
    "$(json_get "${doc}" '[r["windows"][0]["used_pct"] for r in d["rows"] if r["cli"] == "claude"]')" '[10, 91, 55]'
  expect_eq "usage scenario cli: each Z.AI key shows its own quota" \
    "$(json_get "${doc}" '[r["windows"][0]["used_pct"] for r in d["rows"] if r["cli"] == "zai"]')" '[48, 77]'
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema:-${ROOT}/docs/schema/usage-v1.json}" "${doc}")"
  expect_eq "usage scenario cli: the output validates against usage-v1" "${out}" "valid"
  after="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  expect_eq "usage scenario cli: profiles and the env file are untouched" "${before}" "${after}"
  expect_lacks "usage scenario cli: no token or key in the output" "$(cat "${BOX}/out" "${BOX}/err")" "planted-scn-"
  usage_server_stop
}
