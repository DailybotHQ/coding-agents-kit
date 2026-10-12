# shellcheck shell=bash
# Account profiles, ported from the private kit's `profiles` scope and
# driven through the public surface (`ak <kind> @name`, `ak profiles …`).

profiles_env() {
  box_env_file \
    ZAI_CODING_API_KEY=fake-zai-one ZAI_CODING_API_KEY_2=fake-zai-two ZAI_CODING_API_KEY_WORK=fake-zai-work \
    XAI_API_KEY=fake-xai-one XAI_API_KEY_2=fake-xai-two XAI_API_KEY_WORK=fake-xai-work \
    AZURE_OPENAI_API_KEY=fake-azure-one AZURE_OPENAI_API_KEY_2=fake-azure-two AZURE_OPENAI_API_KEY_WORK=fake-azure-work \
    AZURE_OPENAI_RESOURCE=res-one AZURE_OPENAI_MODEL_DAILY=dep-daily
}

# The value a fake reports for one variable.
var_of() {
  printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1
}

scope_profiles() {
  local out status root c args want bad prof dir knob cont row k fam knobvar
  box_new profiles
  box_posture ask  # argv grammar; the permissions scope owns the default
  profiles_env
  root="${BOX}/home/.local/share/agentkit/profiles"

  # --- parsing: only a leading @token is a profile ------------------------
  mkdir -p "${root}/claude/2" "${root}/claude/work" "${root}/claude/readme.md" "${root}/claude/1abc" "${root}/claude/cliente-x"
  local -a cases=(
    "|default|"
    "@2|2|"
    "@2 -c|2|--continue"
    "-c|default|--continue"
    "2|default|2"
    "2 -c|default|2|-c"
    "new|default|new"
    "mcp list|default|mcp|list"
    "@Work|work|"
    "@default|default|"
    "@1|default|"
    "@02|2|"
    "@README.md|readme.md|"
    "@1abc|1abc|"
    "@cliente-x -c|cliente-x|--continue"
    "-- @src/a.ts|default|@src/a.ts"
    "-2|default|-2"
    "@2 -r abc|2|--resume|abc"
  )
  for c in "${cases[@]}"; do
    args="${c%%|*}"; want="${c#*|}"
    # shellcheck disable=SC2086
    out="$(ak -- claude ${args})"
    prof="$(var_of "${out}" CLAUDE_CONFIG_DIR)"
    prof="${prof:+${prof##*/}}"
    if [[ "${prof:-default}|$(argv_of "${out}")" == "${want}" ]]; then
      pass "parse '${args}' -> @${want%%|*} ${want#*|}"
    else
      fail "parse '${args}': got '${prof:-default}|$(argv_of "${out}")', want '${want}'"
    fi
  done
  for bad in "@" "@.." "@.hidden" "@a/b" "@src/a.ts" "@a b" "@2 cats" "@$(printf 'a%.0s' {1..33})" '@x$y' "@../../etc"; do
    out="$(ak -- codex "${bad}")"; status=$?
    if [[ "${status}" -eq 2 && "$(printf '%s\n' "${out}" | wc -l | tr -d ' ')" == 1 && "${out}" == "ak: "*"is not a profile name"* ]]; then
      pass "parse refuses '${bad}' with one line"
    else
      fail "parse refusal for '${bad}' (exit ${status}): ${out}"
    fi
  done
  if [[ -e "${root}/codex" ]]; then fail "a refused name touched the profiles root"; else pass "refused names touch no path"; fi

  # --- AGENTKIT_PROFILE: fallback only; a positional profile wins ----------
  out="$(ak AGENTKIT_PROFILE=@work -- claude -c)"
  expect_eq "AGENTKIT_PROFILE selects the profile" "$(var_of "${out}" CLAUDE_CONFIG_DIR)|$(argv_of "${out}")" "${root}/claude/work|--continue"
  out="$(ak AGENTKIT_PROFILE=work -- claude)"
  expect_eq "AGENTKIT_PROFILE accepts a name without @" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/work"
  out="$(ak AGENTKIT_PROFILE=@work -- claude @2)"
  expect_eq "a positional profile wins over AGENTKIT_PROFILE" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/2"
  out="$(ak AGENTKIT_PROFILE=@a/b -- claude)"; status=$?
  expect_has "an invalid AGENTKIT_PROFILE is an error naming the variable" "${status}:${out}" "2:ak: \"@a/b\" is not a profile name"
  expect_has "the AGENTKIT_PROFILE error names its source" "${out}" "(the name came from AGENTKIT_PROFILE)"

  # --- creation: ask first; only y creates; no terminal names profiles add -
  out="$(printf 'n\n' | box_pipe AGENTKIT_ASSUME_TTY=1 -- bash -c "bash '${ROOT}/bin/ak' claude @newbie" 2>&1)" || true
  if [[ "${out}" == *'claude profile "@newbie" does not exist. Create it? [y/N]'* && "${out}" != *CLI=* && ! -e "${root}/claude/newbie" ]]; then
    pass "answer n: asks, creates nothing, launches nothing"
  else fail "answer n: ${out}"; fi
  out="$(printf '\n' | box_pipe AGENTKIT_ASSUME_TTY=1 -- bash -c "bash '${ROOT}/bin/ak' claude @newbie" 2>&1)" || true
  if [[ "${out}" != *CLI=* && ! -e "${root}/claude/newbie" ]]; then pass "empty answer: creates nothing, launches nothing"; else fail "empty answer: ${out}"; fi
  out="$(printf 'y\n' | box_pipe AGENTKIT_ASSUME_TTY=1 -- bash -c "bash '${ROOT}/bin/ak' claude @newbie" 2>&1)" || true
  if [[ "${out}" == *CLI=claude* && -d "${root}/claude/newbie" && "${out}" == *"created claude profile @newbie at ${root}/claude/newbie"* ]]; then
    pass "answer y: creates the profile and launches"
  else fail "answer y: ${out}"; fi
  expect_eq "profile dir is mode 700" "$(file_mode "${root}/claude/newbie")" 700
  expect_eq "profiles root is mode 700" "$(file_mode "${root}")" 700
  out="$(box_run AGENTKIT_ASSUME_TTY=1 -- bash "${ROOT}/bin/ak" claude @NewBie)"
  if [[ "${out}" != *"[y/N]"* && "${out}" == *CLI=claude* ]]; then pass "an existing profile opens with no question (@NewBie = @newbie)"; else fail "existing profile asked: ${out}"; fi
  out="$(ak -- claude @ghost)"; status=$?
  if [[ "${status}" -eq 3 && "${out}" == *"ak profiles add claude @ghost"* && "${out}" != *CLI=* && ! -e "${root}/claude/ghost" ]]; then
    pass "no terminal: an unknown profile exits 3 naming 'ak profiles add'"
  else fail "no terminal (exit ${status}): ${out}"; fi

  # --- profile 1 changes nothing --------------------------------------------
  box_new profiles-p1
  box_posture ask  # argv grammar; the permissions scope owns the default
  for k in claude codex cursor opencode pi cline grok antigravity; do
    out="$(ak -- "${k}" @default)"
    if [[ -z "$(var_of "${out}" CLAUDE_CONFIG_DIR)$(var_of "${out}" CODEX_HOME)$(var_of "${out}" XDG_DATA_HOME)$(var_of "${out}" PI_CODING_AGENT_DIR)$(var_of "${out}" CLINE_DIR)$(var_of "${out}" GROK_HOME)$(var_of "${out}" AGENT_CLI_CREDENTIAL_STORE)$(var_of "${out}" AGENTKIT_ACTIVE_PROFILE)" \
          && "$(var_of "${out}" HOME)" == "${BOX}/home" ]]; then
      pass "${k} @default exports no isolation knob"
    else fail "${k} @default changed the environment: ${out}"; fi
  done
  if [[ ! -e "${BOX}/home/.local/share/agentkit" ]]; then pass "profile 1 creates no directory"; else fail "profile 1 created the data dir"; fi

  # --- every kind: no profile, @2, @work, with -c ---------------------------
  box_new profiles
  box_posture ask  # argv grammar; the permissions scope owns the default
  profiles_env
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok,antigravity}/{2,work}
  printf '[{"sessionId":"sess-new","cwd":"%s","isSubagent":false,"updatedAt":"2026-10-05T00:00:00Z"}]\n' "${BOX}/work" > "${BOX}/cline-history.json"
  # kind | knob line for profile <P> | continue form
  local -a kinds_table=(
    "claude|CLAUDE_CONFIG_DIR=@DIR|--continue"
    "claude-glm|CLAUDE_CONFIG_DIR=@DIR|--continue"
    "codex|CODEX_HOME=@DIR|resume|--last"
    "codex-azure|CODEX_HOME=@DIR|-p|azure|resume|--last"
    "codex-xai|CODEX_HOME=@DIR|-p|xai|resume|--last"
    "codex-glm|CODEX_HOME=@DIR|-p|glm|resume|--last"
    "cursor|HOME=@DIR/home|--continue"
    "opencode|XDG_DATA_HOME=@DIR/data|--continue"
    "opencode-azure|XDG_DATA_HOME=@DIR/data|-m|azure/dep-daily|--continue"
    "opencode-xai|XDG_DATA_HOME=@DIR/data|-m|xai/grok-4.3|--continue"
    "opencode-glm|XDG_DATA_HOME=@DIR/data|-m|zai-coding-plan/glm-5.3|--continue"
    "pi|PI_CODING_AGENT_DIR=@DIR|--continue"
    "pi-azure|PI_CODING_AGENT_DIR=@DIR|--provider|azure-foundry|--model|dep-daily|--models|azure-foundry/dep-daily|--continue"
    "pi-xai|PI_CODING_AGENT_DIR=@DIR|--provider|xai-grok|--model|grok-4.3|--models|xai-grok/grok-4.3,xai-grok/grok-4.6|--continue"
    "pi-glm|PI_CODING_AGENT_DIR=@DIR|--provider|zai-glm|--model|glm-5.3|--models|zai-glm/glm-5.3,zai-glm/glm-5.3-flash|--continue"
    "cline|CLINE_DIR=@DIR|--id|sess-new"
    "cline-azure|CLINE_DIR=@DIR|-P|openai|-m|dep-daily|-k|fake-azure-@KEY|--id|sess-new"
    "cline-xai|CLINE_DIR=@DIR|-P|openai|-m|grok-4.3|-k|fake-xai-@KEY|--id|sess-new"
    "grok|GROK_HOME=@DIR|--continue"
    "antigravity|HOME=@DIR/home|--continue"
  )
  for row in "${kinds_table[@]}"; do
    k="${row%%|*}"; row="${row#*|}"
    knob="${row%%|*}"; cont="${row#*|}"
    fam="${k%%-*}"
    knobvar="${knob%%=*}"
    for prof in "" "@2" "@work"; do
      # shellcheck disable=SC2086
      ak_split FAKE_CLINE_HISTORY="${BOX}/cline-history.json" -- "${k}" ${prof} -c
      out="$(cat "${BOX}/out")"
      if [[ -z "${prof}" ]]; then
        if [[ "${knobvar}" == HOME ]]; then want="HOME=${BOX}/home"; else want="${knobvar}="; fi
        want_cont="${cont//@KEY/one}"
      else
        dir="${root}/${fam}/${prof#@}"
        want="${knob//@DIR/${dir}}"
        want_cont="${cont//@KEY/$([[ "${prof}" == @2 ]] && echo two || echo work)}"
      fi
      if grep -qxF -- "${want}" <<<"${out}" && [[ "$(argv_of "${out}")" == "${want_cont}" ]]; then
        pass "${k} ${prof:+${prof} }-c -> right account + continue"
      else
        fail "${k} ${prof:+${prof} }-c: want '${want}' and '${want_cont}', got '$(argv_of "${out}")' $(cat "${BOX}/err")"
      fi
    done
  done

  # --- keys reach the CLI per profile, never profile 1's ---------------------
  out="$(ak FAKE_SHOW_SECRETS=1 -- claude-glm @2)"
  expect_line "claude-glm @2 sends ZAI_CODING_API_KEY_2" "${out}" "ANTHROPIC_AUTH_TOKEN=fake-zai-two"
  out="$(ak FAKE_SHOW_SECRETS=1 -- claude-glm)"
  expect_line "claude-glm without a profile sends ZAI_CODING_API_KEY" "${out}" "ANTHROPIC_AUTH_TOKEN=fake-zai-one"
  out="$(ak FAKE_SHOW_SECRETS=1 -- codex-xai @work)"
  expect_line "codex-xai @work sends XAI_API_KEY_WORK as XAI_API_KEY" "${out}" "XAI_API_KEY=fake-xai-work"
  mkdir -p "${root}/claude/7" "${root}/claude/cliente-x" "${root}/grok/9"
  out="$(ak -- claude-glm @7)"; status=$?
  if [[ "${status}" -eq 3 && "${out}" == *"ZAI_CODING_API_KEY_7 is not set"* && "${out}" != *CLI=* && "${out}" != *fake-zai* ]]; then
    pass "claude-glm @7 without ZAI_CODING_API_KEY_7: exit 3 naming it, nothing launched, no value printed"
  else fail "claude-glm @7 (exit ${status}): ${out}"; fi
  out="$(ak ZAI_CODING_API_KEY_CLIENTE_X=fake-zai-cx FAKE_SHOW_SECRETS=1 -- claude-glm @cliente-x)"
  expect_line "@cliente-x reads ZAI_CODING_API_KEY_CLIENTE_X" "${out}" "ANTHROPIC_AUTH_TOKEN=fake-zai-cx"
  out="$(ak FAKE_SHOW_SECRETS=1 -- grok @2)"
  expect_line "grok @2 sends XAI_API_KEY_2" "${out}" "XAI_API_KEY=fake-xai-two"
  out="$(ak FAKE_SHOW_SECRETS=1 -- grok @9)"; status=$?
  expect_eq "grok @9 never falls back to profile 1's key (its own login instead)" "${status}:$(var_of "${out}" XAI_API_KEY)" "0:"
  out="$(ak AZURE_OPENAI_RESOURCE_2=res-two FAKE_SHOW_SECRETS=1 FAKE_LOG="${BOX}/auth2.log" -- cline-azure @2)"
  expect_has "a set companion follows the profile (AZURE_OPENAI_RESOURCE_2)" "$(cat "${BOX}/auth2.log")" "ARG=https://res-two.services.ai.azure.com/openai/v1"
  out="$(ak FAKE_LOG="${BOX}/auth3.log" -- cline-azure @work)"
  expect_has "an unset companion keeps profile 1's non-secret value" "$(cat "${BOX}/auth3.log")" "ARG=https://res-one.services.ai.azure.com/openai/v1"

  # --- antigravity: a HOME per profile; a profile's own account is its key ---
  local ag="${root}/antigravity"
  out="$(ak -- antigravity @2)"
  if [[ -d "${ag}/2/home/.gemini" && ! -L "${ag}/2/home/.gemini" ]] && grep -qx "HOME=${ag}/2/home" <<<"${out}" \
      && grep -qx "GEMINI_API_KEY=" <<<"${out}" && [[ ! -e "${ag}/2/home/.gemini/antigravity-cli/settings.json" ]]; then
    pass "antigravity @2 without a key: its own HOME and .gemini, no key, settings.json untouched (Google login)"
  else fail "antigravity @2 without a key: ${out}"; fi
  out="$(ak GEMINI_API_KEY_WORK=planted-gemini-work FAKE_SHOW_SECRETS=1 -- antigravity @work)"
  local settings="${ag}/work/home/.gemini/antigravity-cli/settings.json"
  if grep -qx "GEMINI_API_KEY=planted-gemini-work" <<<"${out}" \
      && [[ "$(json_get "${settings}" 'd.get("modelProvider")')" == gemini ]] && ! grep -q planted-gemini "${settings}"; then
    pass "antigravity @work with GEMINI_API_KEY_WORK: that key, modelProvider = gemini written, the value never in the file"
  else fail "antigravity @work with its key: ${out} / $(cat "${settings}" 2>/dev/null)"; fi
  printf '{"modelProvider":"gemini","trustedWorkspaces":["/w"]}\n' > "${settings}"
  out="$(ak -- antigravity @work)"
  if [[ "$(json_get "${settings}" '"modelProvider" not in d and d.get("trustedWorkspaces") == ["/w"]')" == true ]]; then
    pass "antigravity @work after its key is gone: modelProvider removed (agy would not start), other settings kept"
  else fail "antigravity @work without its key: $(cat "${settings}")"; fi
  out="$(ak GEMINI_API_KEY=planted-gemini-one FAKE_SHOW_SECRETS=1 -- antigravity @2)"
  expect_line "antigravity @2 never borrows profile 1's GEMINI_API_KEY" "${out}" "GEMINI_API_KEY="
  rm -rf "${root}/antigravity/new"
  ak_split -- profiles add antigravity @new
  expect_has "creating an antigravity profile explains the single keyring login and names its key" \
    "$(cat "${BOX}/err")" "GEMINI_API_KEY_NEW"

  # --- isolation layouts ------------------------------------------------------
  mkdir -p "${BOX}/home/.ssh" "${BOX}/home/.config/gh"; printf 'x\n' > "${BOX}/home/.gitconfig"
  out="$(ak -- cursor @2)"
  if [[ -L "${root}/cursor/2/home/.gitconfig" && -L "${root}/cursor/2/home/.ssh" && -d "${root}/cursor/2/home/.cursor" && ! -L "${root}/cursor/2/home/.cursor" ]] \
      && grep -qx "AGENT_CLI_CREDENTIAL_STORE=file" <<<"${out}" && grep -qx "CURSOR_CONFIG_DIR=${root}/cursor/2/home/.cursor" <<<"${out}"; then
    pass "cursor @2: own .cursor + file credential store, real dotfiles linked in"
  else fail "cursor @2 home layout: ${out}"; fi
  out="$(ak -- opencode @2)"
  if [[ -L "${root}/opencode/2/config/gh" && ! -L "${root}/opencode/2/config/opencode" ]] \
      && grep -qx "XDG_CONFIG_HOME=${root}/opencode/2/config" <<<"${out}" && grep -qx "XDG_STATE_HOME=${root}/opencode/2/state" <<<"${out}"; then
    pass "opencode @2: XDG dirs in the profile, other tools' config linked in, opencode/ kept apart"
  else fail "opencode @2 layout: ${out}"; fi

  # --- writers follow the profile; default configs stay byte-identical -------
  mkdir -p "${BOX}/home/.config/opencode" "${BOX}/home/.pi/agent"
  printf '{"theme":"dark"}\n' > "${BOX}/home/.config/opencode/opencode.json"
  printf '{"providers":{}}\n' > "${BOX}/home/.pi/agent/models.json"
  ak -- codex-glm >/dev/null
  cp "${BOX}/home/.config/opencode/opencode.json" "${BOX}/oc.before"
  cp "${BOX}/home/.pi/agent/models.json" "${BOX}/pi.before"
  cp "${BOX}/home/.codex/glm.config.toml" "${BOX}/codex.before"
  ak -- opencode-xai @2 >/dev/null; ak -- pi-glm @2 >/dev/null; ak -- codex-glm @2 >/dev/null
  if cmp -s "${BOX}/home/.config/opencode/opencode.json" "${BOX}/oc.before" \
      && cmp -s "${BOX}/home/.pi/agent/models.json" "${BOX}/pi.before" \
      && cmp -s "${BOX}/home/.codex/glm.config.toml" "${BOX}/codex.before"; then
    pass "profile @2 writers leave the default configs byte-identical"
  else fail "a profile @2 writer touched the default config"; fi
  check "opencode-xai @2 wrote its provider into the profile" "${AK_PY}" -c "import json,sys; assert 'xai' in json.load(open(sys.argv[1]))['provider']" "${root}/opencode/2/config/opencode/opencode.json"
  check "pi-glm @2 wrote models.json into the profile" "${AK_PY}" -c "import json,sys; assert 'zai-glm' in json.load(open(sys.argv[1]))['providers']" "${root}/pi/2/models.json"
  check "codex-glm @2 wrote its overlay into the profile" test -f "${root}/codex/2/glm.config.toml"

  # --- ak profiles ls | add | path | rm | run ---------------------------------
  box_new profiles-cli
  box_posture ask  # argv grammar; the permissions scope owns the default
  box_env_file ZAI_CODING_API_KEY_2=fake-zai-two
  local kroot="${BOX}/home/.local/share/agentkit/profiles"
  out="$(ak -- profiles)"
  expect_has "profiles ls on a fresh machine says there are none" "${out}" "no profiles yet"
  ak -- profiles add claude-glm @2 >/dev/null
  check "profiles add claude-glm @2 creates claude/2 (kinds share their CLI's profile)" test -d "${kroot}/claude/2"
  ak -- profiles add codex @Work >/dev/null
  check "profiles add codex @Work creates codex/work" test -d "${kroot}/codex/work"
  out="$(ak -- profiles add claude @2)"
  expect_has "profiles add on an existing profile is a no-op" "${out}" "already exists"
  out="$(ak -- profiles add claude @default)"; status=$?
  expect_eq "profiles add @default is refused" "${status}" 2
  out="$(ak -- profiles add claude 2)"; status=$?
  expect_has "profiles add without @ is refused" "${status}:${out}" "2:ak: name the profile with @"
  out="$(ak -- profiles add claude @a/b)"; status=$?
  expect_eq "profiles add refuses an unsafe name" "${status}" 2
  out="$(ak -- profiles add nope @2)"; status=$?
  expect_eq "profiles add refuses an unknown CLI" "${status}" 2
  out="$(ak -- profiles ls)"
  if grep -qE '^claude +@2 +no +ZAI_CODING_API_KEY_2=set' <<<"${out}" && grep -qE '^codex +@work ' <<<"${out}" && [[ "${out}" != *fake-zai* ]]; then
    pass "profiles ls shows CLI, profile, login and keys by name"
  else fail "profiles ls: ${out}"; fi
  printf '{}\n' > "${kroot}/codex/work/auth.json"
  expect_has "profiles ls reports a login from file presence" "$(ak -- profiles ls)" "codex     @work          yes"
  out="$(ak -- profiles path claude @2)"
  expect_eq "profiles path prints the profile directory" "${out}" "${kroot}/claude/2"
  out="$(ak -- profiles path codex @default)"
  expect_eq "profiles path @default prints the CLI's own home" "${out}" "${BOX}/home/.codex"
  out="$(ak -- profiles path claude @9)"; status=$?
  expect_eq "profiles path of a missing profile exits 3" "${status}" 3
  out="$(ak -- profiles rm claude @2)"; status=$?
  if [[ "${status}" -ne 0 && -d "${kroot}/claude/2" && "${out}" == *"--yes"* ]]; then pass "profiles rm without a terminal needs --yes and keeps the profile"; else fail "rm no tty: ${out}"; fi
  out="$(ak -- profiles rm claude @default --yes)"; status=$?
  expect_has "profiles rm refuses @default" "${status}:${out}" "2:ak: refusing to remove @default"
  mkdir -p "${BOX}/outside/keepme"; ln -s "${BOX}/outside" "${kroot}/claude/linked"
  out="$(ak -- profiles rm claude @linked --yes)"; status=$?
  if [[ "${status}" -ne 0 && -d "${BOX}/outside/keepme" ]]; then pass "profiles rm refuses a profile that is a symlink"; else fail "rm followed a symlink"; fi
  out="$(printf 'n\n' | box_pipe AGENTKIT_ASSUME_TTY=1 -- bash -c "bash '${ROOT}/bin/ak' profiles rm claude @2" 2>&1)" || true
  if [[ -d "${kroot}/claude/2" && "${out}" == *"[y/N]"* ]]; then pass "profiles rm asks and keeps the profile on n"; else fail "rm answer n: ${out}"; fi
  out="$(ak -- profiles rm claude @2 --yes)"
  if [[ ! -e "${kroot}/claude/2" && -d "${kroot}/codex/work" && "${out}" == *"Keychain"* ]]; then
    pass "profiles rm --yes removes only that profile (and names Claude's Keychain entry)"
  else fail "profiles rm --yes: ${out}"; fi
  out="$(ak -- profiles run codex @work -- sh -c 'printf "%s" "${CODEX_HOME}"')"
  expect_eq "profiles run executes a command with the profile's knob" "${out}" "${kroot}/codex/work"
  out="$(ak -- profiles run cursor @default sh -c 'printf "%s" "${HOME}"')"
  expect_eq "profiles run @default changes nothing" "${out}" "${BOX}/home"
  out="$(ak -- profiles run codex @nope true)"; status=$?
  if [[ "${status}" -eq 3 && ! -e "${kroot}/codex/nope" && "${out}" == *"ak profiles add codex @nope"* ]]; then
    pass "profiles run on a missing profile exits 3 and creates nothing"
  else fail "profiles run missing: ${out}"; fi
  out="$(ak -- profiles bogus)"; status=$?
  expect_eq "an unknown profiles verb is a usage error" "${status}" 2
  out="$(ak AGENTKIT_PROFILES_DIR="${BOX}/elsewhere" -- profiles add pi @2)"
  check "AGENTKIT_PROFILES_DIR moves the profiles root" test -d "${BOX}/elsewhere/pi/2"

  # --- no fake key value ever lands in a file the kit wrote -------------------
  if grep -rqE 'fake-(zai|xai|azure)-' "${SANDBOX}"/profiles*/home/.local 2>/dev/null; then
    fail "a key value was written under a profiles root"
  else
    pass "no key value written under the profiles root"
  fi
  if grep -rn CODING_AGENT_KIT "${ROOT}/lib" "${ROOT}/bin" >/dev/null 2>&1; then
    fail "the private kit's CODING_AGENT_KIT_ prefix survives in lib/ or bin/"
  else
    pass "every variable uses the AGENTKIT_ prefix"
  fi
  profiles_claude_token
  profiles_json
  profiles_trust_cwd
  profiles_default
  profiles_codex_daemon
}

# Codex records an app-server daemon in its home; a home shared with another
# machine records one that is not here, and only then does ak add --no-daemon.
profiles_codex_daemon() {
  local out root d doc native foreign
  box_new profiles-codex-daemon codex
  box_posture ask
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}/codex/work" "${root}/codex/host"
  d="packages/app-server-daemon/current/bin"
  if [[ "$(uname -s)" == Darwin ]]; then native='\xcf\xfa\xed\xfe'; foreign='\x7fELF'; else native='\x7fELF'; foreign='\xcf\xfa\xed\xfe'; fi

  out="$(ak -- codex)"
  expect_eq "codex daemon: nothing recorded, no flag" "$(argv_of "${out}")" ""
  mkdir -p "${BOX}/home/.codex/${d}"
  printf "${native}rest" > "${BOX}/home/.codex/${d}/codex"; chmod +x "${BOX}/home/.codex/${d}/codex"
  out="$(ak -- codex -c)"
  expect_eq "codex daemon: a daemon built for this OS is reused, no --no-daemon; the account marker goes first" \
    "$(argv_of "${out}")" '-c|shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT="codex/@default"|resume|--last'
  out="$(ak -- codex -- -c 'shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT="codex/@default"')"
  expect_eq "codex daemon: a marker the user passed is not repeated" \
    "$(argv_of "${out}")" '-c|shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT="codex/@default"'
  out="$(ak AGENTKIT_CODEX_NO_DAEMON=1 -- codex)"
  expect_eq "codex daemon: AGENTKIT_CODEX_NO_DAEMON=1 adds --no-daemon anyway" "$(argv_of "${out}")" "--no-daemon"

  mkdir -p "${root}/codex/work/packages/app-server-daemon"
  ln -s "${BOX}/elsewhere/0.158.0" "${root}/codex/work/packages/app-server-daemon/current"
  out="$(ak -- codex @work -c --model x)"
  expect_eq "codex daemon: a recorded daemon that is not here adds --no-daemon, before the user's args" \
    "$(argv_of "${out}")" "resume|--last|--no-daemon|--model|x"
  out="$(ak -- codex @work -- --no-daemon)"
  expect_eq "codex daemon: a --no-daemon the user passed is not repeated" "$(argv_of "${out}")" "--no-daemon"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- codex @work)"
  expect_eq "codex daemon: ... with autonomy" "$(argv_of "${out}")" "--dangerously-bypass-approvals-and-sandbox|--no-daemon"
  mkdir -p "${root}/codex/host/${d}"
  printf "${foreign}rest" > "${root}/codex/host/${d}/codex"; chmod +x "${root}/codex/host/${d}/codex"
  out="$(ak -- codex @host)"
  expect_eq "codex daemon: a daemon built for another OS (a host home in a container) adds --no-daemon" \
    "$(argv_of "${out}")" "--no-daemon"
  mkdir -p "${root}/codex/live/${d}"
  printf "${native}rest" > "${root}/codex/live/${d}/codex"; chmod +x "${root}/codex/live/${d}/codex"
  out="$(ak AGENTKIT_ACTIVE_ACCOUNT=codex/@ghost -- codex @live -c)"
  expect_eq "codex daemon: a reused profile daemon gets that launch's marker (not an inherited one)" \
    "$(argv_of "${out}")" '-c|shell_environment_policy.set.AGENTKIT_ACTIVE_ACCOUNT="codex/@live"|resume|--last'
  out="$(ak AGENTKIT_CODEX_NO_DAEMON=1 -- codex @live)"
  expect_eq "codex daemon: no marker when the daemon is turned off (the shells inherit the launch)" \
    "$(argv_of "${out}")" "--no-daemon"
  mkdir -p "${root}/codex/live2"
  out="$(ak -- codex @live2)"
  expect_eq "codex daemon: no marker when no daemon is recorded (the one codex starts inherits the launch)" \
    "$(argv_of "${out}")" ""

  ak_split -- doctor --json
  doc="${BOX}/doctor.json"; cp "${BOX}/out" "${doc}"
  expect_eq "codex daemon: doctor --json reports each account" "$(json_get "${doc}" 'd["daemons"]')" \
    '{"codex": {"@default": "present", "@host": "missing", "@live": "present", "@live2": "absent", "@work": "missing"}}'
  expect_eq "codex daemon: doctor --json still matches doctor-v1" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/doctor-v1.json" "${doc}")" "valid"
  ak_split AGENTKIT_CODEX_NO_DAEMON=1 -- doctor --json
  expect_eq "codex daemon: doctor --json reports the variable as off" "$(json_get "${BOX}/out" 'd["daemons"]["codex"]["@default"]')" "off"
  ak_split -- doctor
  expect_has "codex daemon: doctor says what ak does" "$(cat "${BOX}/out")" \
    "@work: the daemon its home records is not on this machine; ak codex adds --no-daemon"
}

# A per-CLI default profile (AGENTKIT_DEFAULT_PROFILE_<CLI>): what a bare
# `ak <cli>` launches. @profile, AGENTKIT_PROFILE and an explicit @default win.
profiles_default() {
  local out status root doc
  box_new profiles-default claude codex
  box_posture ask
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}/claude/work" "${root}/claude/2" "${root}/codex/work"
  local D=AGENTKIT_DEFAULT_PROFILE_CLAUDE

  out="$(ak "${D}=@work" -- claude -c)"
  expect_eq "default profile: a bare ak claude launches it" "$(var_of "${out}" CLAUDE_CONFIG_DIR)|$(argv_of "${out}")" "${root}/claude/work|--continue"
  out="$(ak "${D}=work" -- claude)"
  expect_eq "default profile: a name without @ is accepted" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/work"
  out="$(ak "${D}=@work" -- claude @default)"
  expect_eq "default profile: an explicit @default is still the CLI's own home" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" ""
  out="$(ak "${D}=@work" -- claude @2)"
  expect_eq "default profile: a positional profile wins" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/2"
  out="$(ak "${D}=@work" AGENTKIT_PROFILE=@2 -- claude)"
  expect_eq "default profile: AGENTKIT_PROFILE wins over the per-CLI default" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/2"
  out="$(ak "${D}=@default" -- claude)"
  expect_eq "default profile: @default as the value is the CLI's own home" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" ""
  out="$(ak "${D}=@work" -- codex)"
  expect_eq "default profile: another CLI is unaffected" "$(var_of "${out}" CODEX_HOME)" ""
  out="$(ak "${D}=@work" ZAI_CODING_API_KEY=fake-zai-one -- claude-glm)"
  expect_eq "default profile: a provider kind keeps the CLI's own home (its key is per profile)" \
    "$(var_of "${out}" CLAUDE_CONFIG_DIR)" ""

  out="$(ak "${D}=@ghost" -- claude)"; status=$?
  expect_has "default profile: a missing profile is not ready (exit 3), names the variable" "${status}:${out}" \
    "3:ak: claude profile \"@ghost\" does not exist"
  expect_has "default profile: ... and its source" "${out}" "(the name came from ${D})"
  check "default profile: ... and creates nothing, even at a terminal" test ! -e "${root}/claude/ghost"
  out="$(ak "${D}=@a/b" -- claude)"; status=$?
  expect_has "default profile: an invalid value is a usage error naming the variable" "${status}:${out}" \
    "2:ak: ${D}=@a/b is not a profile"

  ak_split "${D}=@work" -- env claude
  expect_has "default profile: ak env follows it" "$(cat "${BOX}/out")" "CLAUDE_CONFIG_DIR=${root}/claude/work"
  printf '{"oauthAccount":{}}' > "${root}/claude/work/.claude.json"     # ak run refuses an account with no login
  ak_split "${D}=@work" FAKE_MODE=headless FAKE_LOG="${BOX}/fake.log" -- run claude --output-format json -- "hello"
  expect_eq "default profile: ak run follows it" "$(var_of "$(cat "${BOX}/fake.log")" CLAUDE_CONFIG_DIR)" "${root}/claude/work"

  # The env file is the configuration: the same key there works.
  box_env_file "${D}=@work"
  out="$(ak -- claude)"
  expect_eq "default profile: the env-file key works" "$(var_of "${out}" CLAUDE_CONFIG_DIR)" "${root}/claude/work"

  ak_split -- profiles --json
  doc="${BOX}/out"
  expect_eq "default profile: profiles --json marks the default account (additive)" \
    "$(json_get "${doc}" '[p["cli"] + " " + p["profile"] for p in d["profiles"] if p.get("default")]')" '["claude @work"]'
  expect_eq "default profile: profiles --json still matches profiles-v1" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/profiles-v1.json" "${doc}")" "valid"
  ak_split -- doctor --json
  doc="${BOX}/out"
  expect_eq "default profile: doctor --json reports it" "$(json_get "${doc}" 'd["default_profiles"]')" '{"claude": "@work"}'
  expect_eq "default profile: doctor --json still matches doctor-v1" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/doctor-v1.json" "${doc}")" "valid"
  ak_split -- doctor
  expect_has "default profile: doctor shows it" "$(cat "${BOX}/out")" "default: ak claude -> @work (${D})"
  box_env_file "${D}=@ghost"
  ak_split -- doctor --json
  expect_has "default profile: doctor names a default that does not exist, with the fix" \
    "$(json_get "${BOX}/out" 'd["problems"]')" "Fix: ak profiles add claude @ghost"

  py_checks default_profile_checks.py
}

# A long-lived Claude token per account (CLAUDE_CODE_OAUTH_TOKEN[_SUFFIX]):
# each profile gets its own as CLAUDE_CODE_OAUTH_TOKEN, never @default's.
profiles_claude_token() {
  local out root
  box_new profiles-token claude
  box_posture ask
  box_env_file CLAUDE_CODE_OAUTH_TOKEN=tok-claude-default CLAUDE_CODE_OAUTH_TOKEN_WORK=tok-claude-work
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}/claude/work" "${root}/claude/bare"

  out="$(ak FAKE_SHOW_SECRETS=1 -- claude @work)"
  expect_eq "profiles claude token: @work gets its own token as CLAUDE_CODE_OAUTH_TOKEN" "$(var_of "${out}" CLAUDE_CODE_OAUTH_TOKEN)" "tok-claude-work"
  out="$(ak FAKE_SHOW_SECRETS=1 -- claude @bare)"
  expect_eq "profiles claude token: a profile without its own token never inherits @default's" "$(var_of "${out}" CLAUDE_CODE_OAUTH_TOKEN)" ""
  out="$(ak FAKE_SHOW_SECRETS=1 -- claude)"
  expect_eq "profiles claude token: @default keeps CLAUDE_CODE_OAUTH_TOKEN" "$(var_of "${out}" CLAUDE_CODE_OAUTH_TOKEN)" "tok-claude-default"
  out="$(ak FAKE_ENV_NAMES=1 -- claude @work)"
  expect_lacks "profiles claude token: the suffixed variable never reaches the CLI" "${out}" "ENVNAME=CLAUDE_CODE_OAUTH_TOKEN_WORK"

  : > "${BOX}/fake.log"
  ak_split FAKE_MODE=headless FAKE_LOG="${BOX}/fake.log" FAKE_SHOW_SECRETS=1 -- run claude @work --output-format json -- "hello"
  expect_eq "profiles claude token: ak run routes the profile's token too" "$(var_of "$(cat "${BOX}/fake.log")" CLAUDE_CODE_OAUTH_TOKEN)" "tok-claude-work"

  out="$(ak -- env claude @bare)"
  expect_has "profiles claude token: ak env blanks the token for a profile without one" "${out}" "CLAUDE_CODE_OAUTH_TOKEN="
  expect_lacks "profiles claude token: ak env never prints a token value" "${out}" "tok-claude"

  out="$(ak FAKE_SHOW_SECRETS=1 -- profiles run claude @work -- claude)"
  expect_eq "profiles claude token: ak profiles run gives the profile its own token" "$(var_of "${out}" CLAUDE_CODE_OAUTH_TOKEN)" "tok-claude-work"
  out="$(ak FAKE_SHOW_SECRETS=1 -- profiles run claude @bare -- claude)"
  expect_eq "profiles claude token: ak profiles run never hands @default's token to another profile" "$(var_of "${out}" CLAUDE_CODE_OAUTH_TOKEN)" ""
  out="$(ak -- profiles run claude @work -- claude --json x)"
  expect_has "profiles claude token: --json after profiles run reaches the command untouched" "${out}" "ARG=--json"
  ak_split -- env claude @work
  expect_has "profiles claude token: ak env prints the profile's token empty" "$(cat "${BOX}/out")" "CLAUDE_CODE_OAUTH_TOKEN="
  expect_has "profiles claude token: ... and says to launch the kind in the pane" "$(cat "${BOX}/err")" "ak claude @work"
  expect_lacks "profiles claude token: ... never the value" "$(cat "${BOX}/out" "${BOX}/err")" "tok-claude-work"

  out="$(ak -- profiles)"
  expect_has "profiles claude token: ak profiles names the token as set" "${out}" "CLAUDE_CODE_OAUTH_TOKEN_WORK=set"
  expect_has "profiles claude token: ... and unset where it is missing" "${out}" "CLAUDE_CODE_OAUTH_TOKEN_BARE=unset"
  expect_has "profiles claude token: a profile with a token counts as logged in" "$(printf '%s\n' "${out}" | grep '@work ')" " yes "
  out="$(ak -- doctor --json)"
  expect_has "profiles claude token: ak doctor lists the token by name" "${out}" "CLAUDE_CODE_OAUTH_TOKEN_WORK"
  expect_lacks "profiles claude token: ... never its value" "${out}" "tok-claude"
}

# `ak profiles --json` (profiles-v1): names and kinds only, portable.
profiles_json() {
  local doc root out
  box_new profiles-json claude codex
  box_env_file CLAUDE_CODE_OAUTH_TOKEN_WORK=tok-json-work ZAI_CODING_API_KEY_WORK=key-json-work
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}/claude/work" "${root}/claude/plain" "${root}/claude/token" "${root}/codex/work"
  printf '{"oauthAccount":{"x":1}}' > "${root}/claude/plain/.claude.json"
  printf '{"oauthAccount":{"x":1}}' > "${root}/claude/token/.claude.json"
  printf '{}' > "${root}/claude/token/.credentials.json"
  printf '{}' > "${root}/codex/work/auth.json"
  doc="${BOX}/profiles.json"
  ak_split -- profiles --json
  cp "${BOX}/out" "${doc}"
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/profiles-v1.json" "${doc}")"
  expect_eq "profiles json: ak profiles --json matches docs/schema/profiles-v1.json" "${out}" "valid"
  expect_eq "profiles json: every account, @default first per CLI" \
    "$(json_get "${doc}" '[(p["cli"], p["profile"]) for p in d["profiles"]]')" \
    '[["claude", "@default"], ["claude", "@plain"], ["claude", "@token"], ["claude", "@work"], ["codex", "@default"], ["codex", "@work"]]'
  expect_eq "profiles json: path is relative to the profiles root; null for @default" \
    "$(json_get "${doc}" '[p["path_relative"] for p in d["profiles"]]')" '[null, "claude/plain", "claude/token", "claude/work", null, "codex/work"]'
  # Claude's .claude.json only names the account: without .credentials.json the
  # token is in the Keychain (macOS; not asked under AGENTKIT_KEYCHAIN=off) or nowhere.
  plain_login="none"; [[ "$(uname -s)" == Darwin ]] && plain_login="unknown"
  expect_eq "profiles json: login kind by presence (token-var, file, none; account file alone is not a file login)" \
    "$(json_get "${doc}" '[p["login"] for p in d["profiles"]]')" "[\"none\", \"${plain_login}\", \"file\", \"token-var\", \"none\", \"file\"]"
  expect_eq "profiles json: key names that are set, never values" \
    "$(json_get "${doc}" '[p["key_names_set"] for p in d["profiles"] if p["profile"] == "@work" and p["cli"] == "claude"][0]')" \
    '["CLAUDE_CODE_OAUTH_TOKEN_WORK", "ZAI_CODING_API_KEY_WORK"]'
  expect_lacks "profiles json: no secret value" "$(cat "${doc}")" "tok-json-work"
  expect_lacks "profiles json: ... nor a key value" "$(cat "${doc}")" "key-json-work"
  expect_lacks "profiles json: no absolute path (the sandbox home never appears)" "$(cat "${doc}")" "${BOX}"
  ak_split -- profiles ls --json
  check "profiles json: ak profiles ls --json is the same" cmp -s "${BOX}/out" "${doc}"
  ak_split -- profiles --json add claude @x; expect_eq "profiles json: --json before another subcommand exits 2" "$?" 2
  ak_split -- profiles
  expect_has "profiles json: the text listing is unchanged" "$(cat "${BOX}/out")" "PROFILE"
}

# --trust-cwd / AGENTKIT_TRUST_CWD=1: pre-trust the launch folder in the
# profile's own CLI config; never without the opt-in.
profiles_trust_cwd() {
  local root cj ct wd out sum1 sum2 other status
  box_new profiles-trust claude codex grok pi
  box_posture ask
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}/claude/work" "${root}/codex/work" "${root}/grok/work"
  cj="${root}/claude/work/.claude.json"; ct="${root}/codex/work/config.toml"
  printf '{"oauthAccount":{"x":1},"theme":"dark"}' > "${cj}"; chmod 600 "${cj}"
  wd="$(cd "${BOX}/work" && pwd -P)"

  ak -- claude @work >/dev/null
  expect_lacks "profiles trust-cwd: without the opt-in nothing is written" "$(cat "${cj}")" "projects"
  out="$(ak -- claude @work --trust-cwd)"
  expect_eq "profiles trust-cwd: claude: the launch folder is trusted in the profile's .claude.json" \
    "$("${AK_PY}" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["projects"][sys.argv[2]]["hasTrustDialogAccepted"]))' "${cj}" "${wd}")" "true"
  expect_eq "profiles trust-cwd: claude: every other key is kept" "$(json_get "${cj}" '[d["theme"], d["oauthAccount"]["x"]]')" '["dark", 1]'
  expect_eq "profiles trust-cwd: claude: the file mode is kept" "$(file_mode "${cj}")" "600"
  expect_has "profiles trust-cwd: one line names the file changed" "${out}" "trusted in ${cj}"
  sum1="$(cksum < "${cj}")"
  out="$(ak -- claude @work --trust-cwd)"
  sum2="$(cksum < "${cj}")"
  expect_eq "profiles trust-cwd: idempotent (a second run changes nothing)" "${sum2}" "${sum1}"
  expect_lacks "profiles trust-cwd: ... and says nothing" "${out}" "trusted in"

  ak AGENTKIT_TRUST_CWD=1 -- codex @work >/dev/null
  expect_has "profiles trust-cwd: codex: AGENTKIT_TRUST_CWD=1 appends the project table" "$(cat "${ct}")" "[projects.\"${wd}\"]"
  expect_has "profiles trust-cwd: codex: ... trusted" "$(cat "${ct}")" 'trust_level = "trusted"'
  ak AGENTKIT_TRUST_CWD=1 -- codex @work >/dev/null
  expect_eq "profiles trust-cwd: codex: idempotent (one table)" "$(grep -c '^\[projects\.' "${ct}")" 1
  other="${BOX}/elsewhere"; mkdir -p "${other}"; other="$(cd "${other}" && pwd -P)"
  printf '[projects."%s"]\ntrust_level = "untrusted"\n' "${other}" >> "${ct}"
  # shellcheck disable=SC2034  # BOX_CWD is read by box_run
  ( BOX_CWD="${other}"; ak -- codex @work --trust-cwd >/dev/null )
  expect_eq "profiles trust-cwd: codex: an existing table is the user's and is left alone" "$(grep -c 'trust_level = "untrusted"' "${ct}")" 1

  out="$(ak FAKE_ENV_NAMES=1 -- claude @work --trust-cwd)"
  expect_has "profiles trust-cwd: the opt-in is inherited by a nested ak" "${out}" "ENVNAME=AGENTKIT_TRUST_CWD"

  mkdir -p "${BOX}/lane"
  ak_split FAKE_MODE=headless -- run claude @work --cwd "${BOX}/lane" --trust-cwd --output-format json -- "hello"
  expect_eq "profiles trust-cwd: ak run trusts its --cwd" \
    "$("${AK_PY}" -c 'import json,sys,os; print(json.load(open(sys.argv[1]))["projects"].get(os.path.realpath(sys.argv[2]), {}).get("hasTrustDialogAccepted"))' "${cj}" "${BOX}/lane")" "True"

  ak -- claude --trust-cwd >/dev/null
  expect_eq "profiles trust-cwd: @default writes the account root's .claude.json (the CLI's own home)" \
    "$("${AK_PY}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["projects"][sys.argv[2]]["hasTrustDialogAccepted"])' "${BOX}/home/.claude.json" "${wd}")" "True"

  # A symlinked config (dotfiles) is updated where it points, inside the profile;
  # a link that leaves the profile is refused.
  mkdir -p "${root}/claude/linked/real"
  printf '{"theme":"light"}' > "${root}/claude/linked/real/claude.json"
  ln -s real/claude.json "${root}/claude/linked/.claude.json"
  ak -- claude @linked --trust-cwd >/dev/null
  check "profiles trust-cwd: a symlinked .claude.json stays a symlink" test -L "${root}/claude/linked/.claude.json"
  expect_has "profiles trust-cwd: ... and its target gets the entry" "$(cat "${root}/claude/linked/real/claude.json")" "hasTrustDialogAccepted"
  mkdir -p "${root}/claude/escape"
  printf '{}' > "${BOX}/outside.json"
  ln -s "${BOX}/outside.json" "${root}/claude/escape/.claude.json"
  ak_split -- claude @escape --trust-cwd; status=$?
  expect_eq "profiles trust-cwd: a link that leaves the profile is refused (exit 3)" "${status}" 3
  expect_eq "profiles trust-cwd: ... and the outside file is untouched" "$(cat "${BOX}/outside.json")" "{}"
  local nl="${BOX}/bad"$'\n'"name"
  mkdir -p "${nl}"
  # shellcheck disable=SC2034  # BOX_CWD is read by ak_split
  ( BOX_CWD="${nl}"; ak_split -- codex @work --trust-cwd; echo "$?" > "${BOX}/nl-status" )
  expect_eq "profiles trust-cwd: a folder name with a control character is refused (exit 2)" "$(cat "${BOX}/nl-status")" 2

  mkdir -p "${root}/pi/work"
  out="$(ak -- pi @work --trust-cwd)"
  expect_has "profiles trust-cwd: a CLI with no known trust screen gets a note" "${out}" "nothing written"
  expect_eq "profiles trust-cwd: ... and nothing is written in its profile" "$(find "${root}/pi/work" -type f | wc -l | tr -d ' ')" 0
  profiles_trust_grok
}

# grok keeps folder trust in <home>/trusted_folders.toml and asks about the
# repository (its main working tree), not the folder it was started in.
profiles_trust_grok() {
  local root gt wd out sum1 repo wt status
  root="${BOX}/home/.local/share/agentkit/profiles"
  gt="${root}/grok/work/trusted_folders.toml"
  wd="$(cd "${BOX}/work" && pwd -P)"
  out="$(ak -- grok @work --trust-cwd)"
  expect_has "profiles trust-cwd: grok: outside a repository the launch folder is trusted" "$(cat "${gt}")" "[folders.\"${wd}\"]"
  expect_eq "profiles trust-cwd: grok: ... as grok records it (trusted, decided_at epoch seconds)" \
    "$(sed -n '2p;3s/[0-9]\{9,\}$/EPOCH/p' "${gt}" | paste -sd '|' -)" "trusted = true|decided_at = EPOCH"
  expect_eq "profiles trust-cwd: grok: a new store is 0600" "$(file_mode "${gt}")" "600"
  expect_has "profiles trust-cwd: grok: one line names the folder and the file" "${out}" "${wd} trusted in ${gt}"
  sum1="$(cksum < "${gt}")"
  ak -- grok @work --trust-cwd >/dev/null
  expect_eq "profiles trust-cwd: grok: idempotent" "$(cksum < "${gt}")" "${sum1}"

  # A repository: from a subfolder, the repository root is the folder asked about.
  repo="${BOX}/repo"; mkdir -p "${repo}/.git" "${repo}/src/deep"; repo="$(cd "${repo}" && pwd -P)"
  # shellcheck disable=SC2034  # BOX_CWD is read by box_run
  ( BOX_CWD="${repo}/src/deep"; ak -- grok @work --trust-cwd >/dev/null )
  expect_has "profiles trust-cwd: grok: from a subfolder the repository root is trusted" "$(cat "${gt}")" "[folders.\"${repo}\"]"
  expect_lacks "profiles trust-cwd: grok: ... not the subfolder" "$(cat "${gt}")" "${repo}/src"

  # A linked worktree (as git writes it): the main working tree is the folder asked about.
  wt="${BOX}/repo/.worktrees/c"; mkdir -p "${repo}/.git/worktrees/c" "${wt}"; wt="$(cd "${wt}" && pwd -P)"
  printf 'gitdir: %s/.git/worktrees/c\n' "${repo}" > "${wt}/.git"
  printf '../..\n' > "${repo}/.git/worktrees/c/commondir"
  printf '[folders."%s"]\ntrusted = false\ndecided_at = 1\n' "${repo}" > "${gt}"
  ( BOX_CWD="${wt}"; ak -- grok @work --trust-cwd >/dev/null )
  expect_eq "profiles trust-cwd: grok: from a linked worktree the main working tree is the folder (an existing answer is left alone)" \
    "$(grep -c '^\[folders\.' "${gt}"):$(grep -c 'trusted = false' "${gt}")" "1:1"
  rm "${gt}"
  ( BOX_CWD="${wt}"; ak -- grok @work --trust-cwd >/dev/null )
  expect_eq "profiles trust-cwd: grok: ... and is written when absent (not the worktree path)" \
    "$(grep '^\[folders\.' "${gt}")" "[folders.\"${repo}\"]"
  if command -v git >/dev/null 2>&1; then
    git init -q "${BOX}/real" && git -C "${BOX}/real" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init \
      && git -C "${BOX}/real" worktree add -q "${BOX}/real-wt" 2>/dev/null
    rm -f "${gt}"
    ( BOX_CWD="${BOX}/real-wt"; ak -- grok @work --trust-cwd >/dev/null )
    expect_eq "profiles trust-cwd: grok: a worktree made by git resolves to its main working tree" \
      "$(grep '^\[folders\.' "${gt}")" "[folders.\"$(cd "${BOX}/real" && pwd -P)\"]"
  fi
  printf 'gitdir: %s/nowhere\n' "${repo}" > "${wt}/.git"
  rm -f "${gt}"
  ( BOX_CWD="${wt}"; ak_split -- grok @work --trust-cwd; echo "$?" > "${BOX}/wt-status" )
  expect_eq "profiles trust-cwd: grok: an unreadable worktree link trusts the worktree itself (never a parent guess)" \
    "$(cat "${BOX}/wt-status"):$(grep '^\[folders\.' "${gt}")" "0:[folders.\"${wt}\"]"
  ak -- grok --trust-cwd >/dev/null
  expect_has "profiles trust-cwd: grok: @default writes grok's own home" "$(cat "${BOX}/home/.grok/trusted_folders.toml")" "[folders.\"${wd}\"]"
  mkdir -p "${root}/grok/escape"
  printf '' > "${BOX}/outside.toml"
  ln -s "${BOX}/outside.toml" "${root}/grok/escape/trusted_folders.toml"
  ak_split -- grok @escape --trust-cwd; status=$?
  expect_eq "profiles trust-cwd: grok: a link that leaves the profile is refused (exit 3), the outside file untouched" \
    "${status}:$(wc -c < "${BOX}/outside.toml" | tr -d ' ')" "3:0"
}
