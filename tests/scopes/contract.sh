# shellcheck shell=bash
# Interface 1, clause by clause: the frozen ecosystem contract for
# coding-agents-kit (§2.0 versioning, §2.1 grammar/kinds/keys/permissions/
# env/run/doctor/env prefix, §5 posture, §9 defaults). Each check names its
# clause, so the contract can be traced to evidence. Detailed behaviour is
# covered by the other scopes; this one proves the surface exists as frozen.

scope_contract() {
  local out status k
  box_new contract
  printf '{"oauthAccount":{}}\n' > "${BOX}/home/.claude.json"
  box_env_file XAI_API_KEY=contract-planted-x XAI_API_KEY_WORK=contract-planted-w

  # §2.0 interface version.
  ak_split -- doctor --json
  expect_eq "§2.0 ak doctor --json -> \"interface\": 1" "$(json_get "${BOX}/out" 'd["interface"]')" 1
  ak_split FAKE_MODE=headless -- run claude --output-format json -- x
  expect_eq "§2.0 the ak run envelope carries interface 1" "$(json_get "${BOX}/out" 'd["interface"]')" 1

  # §2.1 grammar: every frozen form is accepted.
  ak -- profiles add grok @work >/dev/null
  ak -- profiles add claude @work >/dev/null
  local -a forms=(
    "0|claude"
    "0|claude @work -c"
    "0|claude -- -x"
    "0|codex --continue"
    "0|codex -r abc"
    "0|codex --resume abc"
    "0|codex -l"
    "0|run claude --cwd . --timeout 5 --output-format json --auto -- hello"
    "0|env grok @work"
    "0|doctor"
    "0|doctor --json"
    "0|profiles"
    "0|profiles ls"
    "0|profiles add cline @two"
    "0|profiles path cline @two"
    "0|profiles run cline @two -- true"
    "0|profiles rm cline @two --yes"
    "0|alias"
    "0|alias list"
    "0|alias add zz claude"
    "0|alias rm zz"
    "0|alias preset classic --on"
    "0|alias preset classic --off"
    "0|install"
    "0|--skill"
    "0|--version"
  )
  local row want args
  for row in "${forms[@]}"; do
    want="${row%%|*}"; args="${row#*|}"
    # shellcheck disable=SC2086
    ak_split AGENTKIT_NO_RC=1 FAKE_MODE=headless -- ${args}; status=$?
    expect_eq "§2.1 grammar: ak ${args}" "${status}" "${want}"
  done
  ak_split -- install claude; status=$?
  expect_eq "§2.1 grammar: ak install <cli> (installed: skip)" "${status}" 0

  # §2.1 profiles: only a first @ after the kind; @default/@1 = own home; names.
  out="$(ak -- claude x @work)"
  expect_eq "§2.1 only a first argument starting with @ is a profile" "$(argv_of "${out}")" "x|@work"
  for k in @default @1; do
    out="$(ak -- grok "${k}")"
    expect_line "§2.1 ${k} is the CLI's own home" "${out}" "GROK_HOME="
  done
  ak_split -- grok "@$(printf 'a%.0s' {1..33})"; status=$?
  expect_eq "§2.1 profile names are 1-32 of [A-Za-z0-9._-]" "${status}" 2
  ak_split -- grok @.x; status=$?
  expect_eq "§2.1 profile names do not start with ." "${status}" 2
  out="$(ak -- grok @WORK)"
  expect_line "§2.1 profile names are case-insensitive" "${out}" "GROK_HOME=${BOX}/home/.local/share/agentkit/profiles/grok/work"

  # §2.1 kinds table and home variables (detailed in kinds/profiles scopes).
  check "§2.1 the kinds table is data (providers.toml) with all 19 kinds" "${AK_PY}" "${ROOT}/lib/kinds.py" check

  # §2.1 provider keys per profile; missing key names the variable.
  out="$(ak FAKE_SHOW_SECRETS=1 -- grok @work)"
  expect_line "§2.1 <KEY>_<SUFFIX> for a named profile" "${out}" "XAI_API_KEY=contract-planted-w"
  ak -- profiles add codex @nokey >/dev/null
  ak_split -- codex-xai @nokey; status=$?
  expect_has "§2.1 a missing key is an error naming the variable, never a fallback" "${status}:$(cat "${BOX}/err")" "3:ak: XAI_API_KEY_NOKEY is not set"

  # §2.1 / §5 / §9 permissions: pass-through; --auto / AGENTKIT_PERMISSIONS=auto.
  out="$(ak -- claude)"
  expect_eq "§2.1 §9 pass-through by default: no flag added" "$(argv_of "${out}")" ""
  out="$(ak -- claude --auto)"
  expect_eq "§2.1 --auto adds the CLI's own flag" "$(argv_of "${out}")" "--dangerously-skip-permissions"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- grok)"
  expect_eq "§2.1 AGENTKIT_PERMISSIONS=auto adds it" "$(argv_of "${out}")" "--always-approve"
  ak_split -- alias
  expect_has "§9 the classic preset ships off" "$(cat "${BOX}/out")" "classic preset: off"

  # §2.1 ak env: KEY=VALUE only, no secrets, empty = own home.
  ak_split -- env claude
  expect_eq "§2.1 ak env: exit 0 with no output means the CLI's own home" "$(cat "${BOX}/out")" ""
  ak_split -- env grok @work
  if grep -qvE '^[A-Z_][A-Z0-9_]*=' "${BOX}/out" || grep -q 'contract-planted' "${BOX}/out" "${BOX}/err"; then
    fail "§2.1 ak env prints only KEY=VALUE lines without secret values"
  else pass "§2.1 ak env prints only KEY=VALUE lines without secret values"; fi

  # §2.1 ak run: exit codes and envelope keys.
  ak_split FAKE_MODE=headless -- run claude --output-format json -- x
  expect_eq "§2.1 ak run --output-format json: exactly the frozen keys" \
    "$(json_get "${BOX}/out" 'sorted(d)')" '["cli_exit", "cwd", "duration_s", "exit", "interface", "kind", "profile", "result_text", "truncated"]'
  check "§2.1 ak run exit codes 0 1 2 3 4 5 and >= 64 are defined" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import common as c
assert (c.EXIT_OK, c.EXIT_AGENT_FAILED, c.EXIT_USAGE, c.EXIT_NOT_READY, c.EXIT_TIMEOUT, c.EXIT_CANCELLED) == (0, 1, 2, 3, 4, 5)
assert c.EXIT_INTERNAL >= 64' "${ROOT}"
  ak_split FAKE_EXIT=1 -- run claude -- x; status=$?
  expect_eq "§2.1 ak run exit 1: the agent finished and reported failure" "${status}" 1
  ak_split -- run claude; status=$?
  expect_eq "§2.1 ak run exit 2: usage" "${status}" 2

  # §2.1 doctor --json top-level keys.
  ak_split -- doctor --json
  expect_eq "§2.1 doctor --json has every contract key" \
    "$(json_get "${BOX}/out" 'all(k in d for k in ["interface","version","os","kinds","profiles","keys","permissions","aliases","herdr_hooks"])')" true
  expect_eq "§2.1 doctor kinds carry installed/version/logged_in" \
    "$(json_get "${BOX}/out" 'all({"installed","version","logged_in"} <= set(v) for v in d["kinds"].values())')" true
  expect_lacks "§2.1 doctor keys are names, never values" "$(cat "${BOX}/out")" "contract-planted"

  # §2.1 env prefix and paths.
  ak_split AGENTKIT_PROFILES_DIR="${BOX}/pdir" -- profiles add pi @p
  check "§2.1 AGENTKIT_PROFILES_DIR is honoured" test -d "${BOX}/pdir/pi/p"
  printf 'XAI_API_KEY=from-alt-file\n' > "${BOX}/alt.env"; chmod 600 "${BOX}/alt.env"
  out="$(ak AGENTKIT_ENV="${BOX}/alt.env" FAKE_SHOW_SECRETS=1 -- grok)"
  expect_line "§2.1 AGENTKIT_ENV selects the env file" "${out}" "XAI_API_KEY=from-alt-file"
  out="$(ak AGENTKIT_PROFILE=@work -- grok)"
  expect_line "§2.1 AGENTKIT_PROFILE selects the profile" "${out}" "GROK_HOME=${BOX}/home/.local/share/agentkit/profiles/grok/work"
  ak_split AGENTKIT_HOME="${BOX}/akhome" -- profiles add pi @q
  check "§2.1 AGENTKIT_HOME moves the data dir (profiles under it)" test -d "${BOX}/akhome/profiles/pi/q"
  check "§2.1 profiles live in ~/.local/share/agentkit/profiles by default" test -d "${BOX}/home/.local/share/agentkit/profiles/grok/work"
  check "§2.1 the env file is ~/.config/agentkit/env by default" grep -q '^XAI_API_KEY=' "${BOX}/home/.config/agentkit/env"
  expect_eq "§2.1 the env file is mode 600" "$(file_mode "${BOX}/home/.config/agentkit/env")" 600
  if grep -rn 'CODING_AGENT_KIT\|CAK_' "${ROOT}/lib" "${ROOT}/bin" >/dev/null; then
    fail "§2.1 every variable uses the AGENTKIT_ prefix"
  else pass "§2.1 every variable uses the AGENTKIT_ prefix"; fi

  # Standalone (the product never needs DeepWorkPlan).
  if grep -rIlE '\.dwp/|deepworkplan' "${ROOT}/bin" "${ROOT}/lib" "${ROOT}/providers.toml" "${ROOT}/install.sh" \
      "${ROOT}/install.ps1" "${ROOT}/win" "${ROOT}/skills" >/dev/null; then
    fail "the product works without DeepWorkPlan (no .dwp/ or deepworkplan reference in runtime files)"
  else pass "the product works without DeepWorkPlan (no .dwp/ or deepworkplan reference in runtime files)"; fi
}
