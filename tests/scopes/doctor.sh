# shellcheck shell=bash
# `ak env` (KEY=VALUE only, no secrets) and `ak doctor [--json]` (interface 1).

PLANTED_VALUES="planted-zai-0x1 planted-zai-0x2 planted-xai-0x1 planted-xai-0x2 planted-azure-0x1 planted-azure-0x2"

doctor_env_file() {
  box_env_file ZAI_CODING_API_KEY=planted-zai-0x1 ZAI_CODING_API_KEY_2=planted-zai-0x2 \
    XAI_API_KEY=planted-xai-0x1 XAI_API_KEY_2=planted-xai-0x2 \
    AZURE_OPENAI_API_KEY=planted-azure-0x1 AZURE_OPENAI_API_KEY_2=planted-azure-0x2 \
    AZURE_OPENAI_RESOURCE=res AZURE_OPENAI_MODEL_DAILY=dep
}

# no_planted <text> — true when no planted value appears.
no_planted() {
  local v
  for v in ${PLANTED_VALUES}; do
    [[ "$1" == *"${v}"* ]] && return 1
  done
  return 0
}

scope_doctor() {
  local out err status root k doc schema="${ROOT}/docs/schema/doctor-v1.json"
  box_new doctor
  doctor_env_file
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok}/work "${root}/grok/9"
  doc="${BOX}/doctor.json"

  # --- doctor --json: schema, interface, contents -----------------------------
  ak_split -- doctor --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "doctor --json exits 0" "${status}" 0
  check "doctor --json is one JSON object" "${AK_PY}" -c 'import json,sys; assert isinstance(json.load(open(sys.argv[1])), dict)' "${doc}"
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")"
  expect_eq "doctor --json matches docs/schema/doctor-v1.json" "${out}" "valid"
  expect_eq "doctor reports interface 1" "$(json_get "${doc}" 'd["interface"]')" 1
  expect_eq "doctor reports the kit version" "$(json_get "${doc}" 'd["version"]')" "0.2.1"
  expect_eq "doctor reports this OS" "$(json_get "${doc}" 'd["os"] in ("macos", "linux")')" true
  expect_eq "doctor lists all 19 kinds" "$(json_get "${doc}" 'len(d["kinds"])')" 19
  expect_eq "doctor sees the installed CLIs" "$(json_get "${doc}" 'all(v["installed"] for v in d["kinds"].values())')" true
  expect_eq "doctor reads each CLI's version" "$(json_get "${doc}" 'd["kinds"]["codex"]["version"]')" "codex 0.0.0-fake"
  expect_eq "doctor lists profiles per CLI" "$(json_get "${doc}" 'd["profiles"]["grok"]')" '["9", "work"]'
  expect_eq "doctor lists key names (base and per profile)" \
    "$(json_get "${doc}" 'd["keys"]')" '["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_KEY_2", "XAI_API_KEY", "XAI_API_KEY_2", "ZAI_CODING_API_KEY", "ZAI_CODING_API_KEY_2"]'
  expect_eq "provider kinds are logged in when their key is set" "$(json_get "${doc}" 'd["kinds"]["claude-glm"]["logged_in"]')" true
  expect_eq "permissions default to auto" "$(json_get "${doc}" 'd["permissions"]')" auto
  expect_eq "the classic preset is off by default" "$(json_get "${doc}" 'd["aliases"]')" '{"classic": false, "custom": []}'
  expect_eq "herdr hooks are reported per profile" "$(json_get "${doc}" 'd["herdr_hooks"]["claude"]')" '{"@default": "absent", "@work": "absent"}'
  expect_eq "cline (no Herdr integration) has no hook entry" "$(json_get "${doc}" '"cline" in d["herdr_hooks"]')" false
  expect_eq "the env file mode is reported" "$(json_get "${doc}" 'd["env_file"]["mode"]')" 600
  if no_planted "$(cat "${BOX}/out" "${BOX}/err")"; then pass "doctor --json prints no key value"; else fail "doctor --json printed a key value"; fi

  # Login from file presence only.
  expect_eq "claude without an account file: not logged in" "$(json_get "${doc}" 'd["kinds"]["claude"]["logged_in"]')" false
  printf '{"oauthAccount":{"emailAddress":"x"}}\n' > "${BOX}/home/.claude.json"
  mkdir -p "${BOX}/home/.codex"; printf '{}\n' > "${BOX}/home/.codex/auth.json"
  ak_split -- doctor --json; cp "${BOX}/out" "${doc}"
  expect_eq "claude with ~/.claude.json naming an account: logged in" "$(json_get "${doc}" 'd["kinds"]["claude"]["logged_in"]')" true
  expect_eq "codex with auth.json: logged in" "$(json_get "${doc}" 'd["kinds"]["codex"]["logged_in"]')" true
  expect_eq "opencode login cannot be told from files: null" "$(json_get "${doc}" 'd["kinds"]["opencode"]["logged_in"]')" null
  mkdir -p "${BOX}/home/.claude/hooks"; printf '#!/bin/sh\n' > "${BOX}/home/.claude/hooks/herdr-agent-state.sh"
  ak_split -- doctor --json; cp "${BOX}/out" "${doc}"
  expect_eq "herdr hooks present in the default home are reported" "$(json_get "${doc}" 'd["herdr_hooks"]["claude"]["@default"]')" present

  # Posture and problems.
  ak_split AGENTKIT_PERMISSIONS=auto -- doctor --json
  expect_eq "doctor reports permissions auto" "$(json_get "${BOX}/out" 'd["permissions"]')" auto
  ak_split AGENTKIT_PERMISSIONS=bogus -- doctor --json
  expect_eq "an invalid posture is reported as ask, with a problem" \
    "$(json_get "${BOX}/out" '[d["permissions"], any("AGENTKIT_PERMISSIONS" in p for p in d["problems"])]')" '["ask", true]'
  chmod 644 "${BOX}/home/.config/agentkit/env"
  ak_split -- doctor --json
  expect_eq "a readable env file is a problem" "$(json_get "${BOX}/out" 'any("chmod 600" in p for p in d["problems"])')" true
  chmod 600 "${BOX}/home/.config/agentkit/env"

  # A CLI that is not installed.
  box_new doctor-missing claude
  ak_split -- doctor --json
  expect_eq "a missing CLI: installed false, version null" "$(json_get "${BOX}/out" '[d["kinds"]["pi"]["installed"], d["kinds"]["pi"]["version"]]')" '[false, null]'
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${BOX}/out")"
  expect_eq "a fresh machine's doctor --json still matches the schema" "${out}" "valid"
  out="$(ak -- doctor)"; status=$?
  expect_eq "text doctor exits 0" "${status}" 0
  expect_has "text doctor names the install command for a missing CLI" "${out}" "not installed — ak install pi"
  expect_has "text doctor states the posture" "${out}" "permissions: auto"
  expect_has "text doctor names the opt-out" "${out}" "opt out with --ask or AGENTKIT_PERMISSIONS=ask"
  expect_has "text doctor warns about autonomy outside a container" "${out}" "autonomy is meant for disposable or sandboxed environments"
  out="$(ak -- doctor --bogus)"; status=$?
  expect_eq "doctor with an unknown option is a usage error" "${status}" 2

  # --- ak env ---------------------------------------------------------------------
  box_new doctor
  doctor_env_file
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok}/work "${root}/grok/9" "${root}/claude/2"
  ak_split -- env claude; status=$?
  expect_eq "ak env claude (@default): exit 0, no output = the CLI's own home" "${status}:$(cat "${BOX}/out")" "0:"
  ak_split -- env claude @work
  expect_eq "ak env claude @work" "$(cat "${BOX}/out")" "CLAUDE_CONFIG_DIR=${root}/claude/work"
  ak_split -- env codex @work
  expect_eq "ak env codex @work" "$(cat "${BOX}/out")" "CODEX_HOME=${root}/codex/work"
  ak_split -- env pi @work
  expect_eq "ak env pi @work" "$(cat "${BOX}/out")" "PI_CODING_AGENT_DIR=${root}/pi/work"
  ak_split -- env cline @work
  expect_eq "ak env cline @work" "$(cat "${BOX}/out")" "CLINE_DIR=${root}/cline/work"
  ak_split -- env cursor @work
  expect_eq "ak env cursor @work" "$(cat "${BOX}/out")" "$(printf 'AGENT_CLI_CREDENTIAL_STORE=file\nCURSOR_CONFIG_DIR=%s\nHOME=%s' "${root}/cursor/work/home/.cursor" "${root}/cursor/work/home")"
  ak_split -- env opencode @work
  expect_eq "ak env opencode @work sets the four XDG directories" "$(cut -d= -f1 "${BOX}/out" | tr '\n' ' ')" "XDG_CACHE_HOME XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME "
  ak_split AGENTKIT_PROFILE=@work -- env grok
  expect_eq "ak env honours AGENTKIT_PROFILE" "$(head -1 "${BOX}/out")" "GROK_HOME=${root}/grok/work"
  ak_split -- env grok @9
  expect_eq "ak env grok @9 blanks profile 1's inherited key" "$(cat "${BOX}/out")" "$(printf 'GROK_HOME=%s\nXAI_API_KEY=' "${root}/grok/9")"
  ak_split -- env claude-glm @2; status=$?
  out="$(cat "${BOX}/out")"; err="$(cat "${BOX}/err")"
  expect_eq "ak env claude-glm @2 exits 0" "${status}" 0
  expect_line "ak env claude-glm carries the non-secret provider settings" "${out}" "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic"
  expect_lacks "ak env never prints the secret-bearing variable" "${out}" "ANTHROPIC_AUTH_TOKEN"
  expect_has "ak env names the omitted secret variable on stderr" "${err}" "ANTHROPIC_AUTH_TOKEN is not printed"
  ak_split -- env codex-azure @work
  expect_has "ak env explains what an environment cannot carry (args, writer)" "$(cat "${BOX}/err")" "run \`ak codex-azure @work\` in the pane"
  ak_split -- env claude @ghost; status=$?
  expect_eq "ak env of a missing profile exits 3" "${status}" 3
  ak_split -- env nope; status=$?
  expect_eq "ak env of an unknown kind is a usage error" "${status}" 2
  ak_split -- env claude @work extra; status=$?
  expect_eq "ak env with extra arguments is a usage error" "${status}" 2
  box_new doctor-nokeys
  ak_split -- env claude-glm; status=$?
  expect_eq "ak env needs no key (it never reads one)" "${status}" 0

  # Every kind × profile: only KEY=VALUE lines, never a planted value.
  box_new doctor
  doctor_env_file
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok}/2
  local bad_lines=0 leaked=0 n=0
  for k in claude claude-glm codex codex-glm codex-azure codex-xai cursor opencode opencode-glm opencode-azure opencode-xai \
      pi pi-glm pi-azure pi-xai cline cline-azure cline-xai grok; do
    for p in "" "@2"; do
      # shellcheck disable=SC2086
      ak_split -- env "${k}" ${p}
      n=$((n + 1))
      grep -qvE '^[A-Z_][A-Z0-9_]*=' "${BOX}/out" && bad_lines=$((bad_lines + 1))
      grep -q '^export ' "${BOX}/out" && bad_lines=$((bad_lines + 1))
      no_planted "$(cat "${BOX}/out" "${BOX}/err")" || leaked=$((leaked + 1))
    done
  done
  expect_eq "ak env prints only KEY=VALUE lines for all ${n} kind/profile pairs" "${bad_lines}" 0
  expect_eq "ak env prints no planted key value for all ${n} kind/profile pairs" "${leaked}" 0
  out="$(ak -- doctor)"
  if no_planted "${out}"; then pass "text doctor prints no key value"; else fail "text doctor printed a key value"; fi
  expect_has "text doctor lists key names" "${out}" "ZAI_CODING_API_KEY_2"

  # --- ak env import: keys from another env file, safely -------------------------------
  box_new env-import
  box_env_file XAI_API_KEY=planted-kept-1
  printf '%s\n' '# legacy file' 'export ZAI_CODING_API_KEY="planted-import-2"' 'XAI_API_KEY=planted-other-3' \
    'EMPTY=' 'if true; then :; fi' 'OPENAI_API_KEY_WORK=planted-import-4' \
    'RUN_A=$(touch planted-ran-a)' 'RUN_B=ok; touch planted-ran-b' 'RUN_C="`touch planted-ran-c`"' > "${BOX}/legacy"
  chmod 600 "${BOX}/legacy"
  out="$(ak -- env import "${BOX}/legacy")"; status=$?
  expect_eq "ak env import succeeds" "${status}" 0
  expect_has "it names the keys it imported" "${out}" "ZAI_CODING_API_KEY, OPENAI_API_KEY_WORK"
  expect_has "an existing key is skipped, not overwritten" "${out}" "skipped XAI_API_KEY: already set"
  expect_has "shell code is not imported" "${out}" "not a KEY=value line"
  expect_has "an empty value is skipped" "${out}" "skipped EMPTY: empty"
  check "the existing value is untouched" grep -qx 'XAI_API_KEY=planted-kept-1' "${BOX}/home/.config/agentkit/env"
  check "the other file's value for an existing key is not copied" bash -c "! grep -q planted-other-3 '${BOX}/home/.config/agentkit/env'"
  check "profile-suffixed keys are kept as they are" grep -qx "OPENAI_API_KEY_WORK='planted-import-4'" "${BOX}/home/.config/agentkit/env"
  check "a quoted value is written as a plain single-quoted literal" grep -qx "ZAI_CODING_API_KEY='planted-import-2'" "${BOX}/home/.config/agentkit/env"
  expect_has "a command substitution is refused" "${out}" "skipped RUN_A: the value is shell code"
  expect_has "a value with ; is refused" "${out}" "skipped RUN_B: the value is shell code"
  expect_has "a value with backquotes is refused" "${out}" "skipped RUN_C: the value is shell code"
  check "no shell code reached the env file" bash -c "! grep -q 'RUN_' '${BOX}/home/.config/agentkit/env'"
  ak -- doctor >/dev/null
  check "loading the env file afterwards ran nothing" bash -c "! ls '${BOX}/work' '${BOX}/home' | grep -q planted-ran"
  expect_eq "the env file stays mode 600" "$(file_mode "${BOX}/home/.config/agentkit/env")" 600
  expect_lacks "no planted value is printed" "${out}" "planted-"
  out="$(ak -- env import "${BOX}/legacy")"
  expect_has "a second import adds nothing" "${out}" "imported into ${BOX}/home/.config/agentkit/env: nothing"
  chmod 666 "${BOX}/legacy"
  out="$(ak -- env import "${BOX}/legacy")"; status=$?
  expect_eq "a group- or world-writable source is refused" "${status}" 2
  expect_lacks "a refusal prints no value either" "${out}" "planted-"
  rm -f "${BOX}/home/.config/agentkit/env"
  chmod 600 "${BOX}/legacy"
  out="$(ak -- env import "${BOX}/legacy")"
  expect_eq "a missing env file is created mode 600" "$(file_mode "${BOX}/home/.config/agentkit/env")" 600
  out="$(ak -- env import)"; status=$?
  expect_eq "ak env import without a file is a usage error" "${status}" 2
}
