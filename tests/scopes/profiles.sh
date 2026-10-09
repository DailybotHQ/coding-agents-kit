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
  for k in claude codex cursor opencode pi cline grok; do
    out="$(ak -- "${k}" @default)"
    if [[ -z "$(var_of "${out}" CLAUDE_CONFIG_DIR)$(var_of "${out}" CODEX_HOME)$(var_of "${out}" XDG_DATA_HOME)$(var_of "${out}" PI_CODING_AGENT_DIR)$(var_of "${out}" CLINE_DIR)$(var_of "${out}" GROK_HOME)$(var_of "${out}" AGENT_CLI_CREDENTIAL_STORE)$(var_of "${out}" AGENTKIT_ACTIVE_PROFILE)" \
          && "$(var_of "${out}" HOME)" == "${BOX}/home" ]]; then
      pass "${k} @default exports no isolation knob"
    else fail "${k} @default changed the environment: ${out}"; fi
  done
  if [[ ! -e "${BOX}/home/.local/share/agentkit" ]]; then pass "profile 1 creates no directory"; else fail "profile 1 created the data dir"; fi

  # --- every kind: no profile, @2, @work, with -c ---------------------------
  box_new profiles
  profiles_env
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok}/{2,work}
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
}
