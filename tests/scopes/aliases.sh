# shellcheck shell=bash
# `ak alias`: custom aliases, the classic preset (off by default), the
# generated aliases.sh and the guarded rc block.

scope_aliases() {
  local out status script cfg
  box_new aliases
  printf '# mine\nalias ll="ls -l"\n' > "${BOX}/home/.zshrc"
  script="${BOX}/home/.local/share/agentkit/aliases.sh"
  cfg="${BOX}/home/.config/agentkit/aliases.json"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/work"

  out="$(ak -- alias)"
  expect_has "ak alias lists the classic preset as off by default" "${out}" "classic preset: off"
  out="$(ak -- doctor --json)"
  # (doctor output parsed below with the alias state)

  # --- classic preset ------------------------------------------------------------
  out="$(ak SHELL=/bin/zsh -- alias preset classic --on)"; status=$?
  expect_eq "preset classic --on exits 0" "${status}" 0
  expect_has "turning the preset on says the names follow the posture" "${out}" "autonomy follows your posture"
  check "aliases.json records the preset" grep -q '"classic": true' "${cfg}"
  expect_eq "aliases.json is mode 600" "$(file_mode "${cfg}")" 600
  for a in claudex codexx cursorx opencodex pix clinex grokx; do
    check "classic defines ${a}" grep -q "^${a}() {" "${script}"
  done
  check "no classic alias spells --auto or --ask (plain names)" bash -c "! grep -E -- '--(auto|ask)' '${script}'"
  check "aliases.sh is valid sh" sh -n "${script}"
  out="$(box_run -- bash -c ". '${script}'; claudex @work -c")"
  expect_eq "claudex @work -c runs ak claude @work -c (default autonomy)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  out="$(box_run AGENTKIT_PERMISSIONS=ask -- bash -c ". '${script}'; claudex @work -c")"
  expect_eq "claudex honours the opt-out" "$(argv_of "${out}")" "--continue"
  expect_line "claudex keeps the profile" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/work"
  out="$(box_run -- bash -c ". '${script}'; codexx -l")"
  expect_eq "codexx -l runs codex resume --last with its autonomy flag" "$(argv_of "${out}")" "resume|--last|--dangerously-bypass-approvals-and-sandbox"
  expect_eq "turning an alias layer on adds the rc block once" "$(grep -c '^# >>> agentkit >>>$' "${BOX}/home/.zshrc")" 1
  check "the rc block sources aliases.sh" grep -qF ". '${script}'" "${BOX}/home/.zshrc"
  out="$(box_run -- zsh -c ". '${BOX}/home/.zshrc'; whence -w grokx" 2>/dev/null || box_run -- bash -c ". '${BOX}/home/.zshrc'; type -t grokx")"
  expect_has "a new shell has the aliases" "${out}" "function"
  ak_split -- doctor --json
  expect_eq "doctor reports the classic preset on" "$(json_get "${BOX}/out" 'd["aliases"]["classic"]')" true
  ak -- alias preset classic --off >/dev/null
  if grep -q '^claudex() {' "${script}"; then fail "preset classic --off left claudex defined"; else pass "preset classic --off removes the classic aliases"; fi
  out="$(ak -- alias preset classic)"
  expect_has "preset classic reports its state" "${out}" "off"
  out="$(ak -- alias preset modern --on)"; status=$?
  expect_eq "an unknown preset is a usage error" "${status}" 2

  # --- custom aliases --------------------------------------------------------------------
  out="$(ak -- alias add work_claude claude @Work --auto)"; status=$?
  expect_has "alias add defines a custom alias" "${status}:${out}" "0:added work_claude -> ak claude @work --auto"
  out="$(box_run -- bash -c ". '${script}'; work_claude -c")"
  expect_eq "the custom alias runs its kind, profile and posture" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  expect_line "the custom alias uses its profile" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/work"
  ak -- alias add glm claude-glm >/dev/null
  out="$(box_run ZAI_CODING_API_KEY=k -- bash -c ". '${script}'; glm")"
  expect_eq "a custom alias without a posture follows the default (autonomy)" "$(argv_of "${out}")" "--dangerously-skip-permissions"
  out="$(ak -- alias add careful claude --ask)"
  expect_has "alias add records an --ask posture" "${out}" "added careful -> ak claude --ask"
  out="$(box_run -- bash -c ". '${script}'; careful")"
  expect_eq "a custom alias with --ask adds no autonomy flag" "$(argv_of "${out}")" ""
  out="$(ak -- alias add both claude --ask --auto)"; status=$?
  expect_eq "alias add refuses --ask with --auto" "${status}" 2
  out="$(ak -- alias add glm codex)"
  expect_has "adding an existing name replaces it" "${out}" "replaced glm"
  out="$(ak -- alias list)"
  expect_has "alias list shows custom aliases" "${out}" "work_claude"
  ak_split -- doctor --json
  expect_eq "doctor lists custom alias names" "$(json_get "${BOX}/out" 'd["aliases"]["custom"]')" '["careful", "glm", "work_claude"]'
  for bad in "ak claude" "claude claude" "agent cursor" "1abc claude" "a/b claude" "my-claude claude" "x nope" "x claude @a/b" "x claude extra"; do
    # shellcheck disable=SC2086
    out="$(ak -- alias add ${bad})"; status=$?
    expect_eq "alias add refuses '${bad}'" "${status}" 2
  done
  ak -- alias preset classic --on >/dev/null
  out="$(ak -- alias add claudex codex)"; status=$?
  expect_eq "a custom alias cannot take a classic name while the preset is on" "${status}" 2
  ak -- alias preset classic --off >/dev/null
  ak -- alias add claudex codex >/dev/null
  out="$(ak -- alias preset classic --on)"; status=$?
  expect_eq "the preset refuses to shadow a custom alias with a classic name" "${status}" 2
  ak -- alias rm claudex >/dev/null
  out="$(ak -- alias rm glm)"; status=$?
  expect_eq "alias rm removes a custom alias" "${status}:$(grep -c '^glm() {' "${script}")" "0:0"
  out="$(ak -- alias rm nope)"; status=$?
  expect_eq "alias rm of an unknown name exits 3" "${status}" 3

  # --- the rc block ---------------------------------------------------------------------
  expect_eq "the rc block is still single after many alias changes" "$(grep -c '^# >>> agentkit >>>$' "${BOX}/home/.zshrc")" 1
  check "the user's own rc line survives" grep -q '^alias ll="ls -l"$' "${BOX}/home/.zshrc"
  out="$(ak -- alias rc --print)"
  expect_has "alias rc --print shows the block" "${out}" "# <<< agentkit <<<"
  ak -- alias rc --remove >/dev/null
  expect_eq "alias rc --remove restores the rc exactly" "$(cat "${BOX}/home/.zshrc")" "$(printf '# mine\nalias ll="ls -l"')"
  box_new aliases-norc
  ak AGENTKIT_NO_RC=1 -- alias add w claude >/dev/null
  if [[ -e "${BOX}/home/.zshrc" || -e "${BOX}/home/.bashrc" || -e "${BOX}/home/.profile" ]]; then fail "AGENTKIT_NO_RC=1 still wrote an rc"; else pass "AGENTKIT_NO_RC=1 keeps ak alias away from shell rc files"; fi
  box_new aliases-profile
  ak -- alias add w claude >/dev/null
  check "with no rc file at all, the block goes to ~/.profile" grep -q '^# >>> agentkit >>>$' "${BOX}/home/.profile"

  # --- the providers preset: dash-named shortcuts, bash and zsh only -------------------
  box_new aliases-providers
  script="${BOX}/home/.local/share/agentkit/aliases.sh"
  out="$(ak -- alias preset providers --on)"
  expect_has "the providers preset turns on" "${out}" "providers preset on (bash and zsh): claude-glm"
  check "aliases.sh stays valid sh with the providers preset" sh -n "${script}"
  for k in claude-glm codex-glm codex-azure codex-xai opencode-glm opencode-azure opencode-xai pi-glm pi-azure pi-xai cline-azure cline-xai; do
    check "bash defines ${k}" bash -c ". '${script}'; [ \"\$(type -t ${k})\" = function ]"
  done
  if command -v zsh >/dev/null 2>&1; then
    check "zsh defines codex-glm" zsh -c ". '${script}'; whence -w codex-glm | grep -q function"
  fi
  if command -v dash >/dev/null 2>&1; then
    check "dash (POSIX sh) sources the file without defining a dash name" \
      env -i PATH="${BASE_PATH}" dash -c ". '${script}'; ! command -v codex-glm >/dev/null 2>&1"
  else
    skip "dash (POSIX sh) sources the file without defining a dash name (no dash on this machine)"
  fi
  out="$(box_run ZAI_CODING_API_KEY=fake-zai -- bash -c ". '${script}'; codex-glm -c")"
  expect_eq "codex-glm runs ak codex-glm (default autonomy)" "$(argv_of "${out}")" "-p|glm|resume|--last|--dangerously-bypass-approvals-and-sandbox"
  out="$(box_run ZAI_CODING_API_KEY=fake-zai AGENTKIT_PERMISSIONS=ask -- bash -c ". '${script}'; codex-glm -c")"
  expect_eq "codex-glm honours the opt-out" "$(argv_of "${out}")" "-p|glm|resume|--last"
  ak_split -- doctor --json
  expect_eq "doctor reports the providers preset" "$(json_get "${BOX}/out" 'd["aliases"]["providers"]')" "true"
  out="$(ak -- alias preset providers --off)"
  check "turning the providers preset off removes the definitions" bash -c "! grep -q 'codex-glm' '${script}'"
  out="$(ak -- alias preset nope --on)"; status=$?
  expect_eq "an unknown preset is a usage error" "${status}" 2
}
