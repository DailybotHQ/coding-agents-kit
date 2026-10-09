# shellcheck shell=bash
# Permission posture: autonomy by default (the CLI's own autonomy flag on
# every launch), with an opt-out that always wins: --ask or
# AGENTKIT_PERMISSIONS=ask.

AUTONOMY_FLAGS="--dangerously-skip-permissions --dangerously-bypass-approvals-and-sandbox --force --yolo --auto --approve --always-approve"

# The autonomy flags present in an argv (one per line).
autonomy_in() {
  local argv="$1" f
  for f in ${AUTONOMY_FLAGS}; do
    printf '%s\n' "${argv}" | tr '|' '\n' | grep -cxF -- "${f}" | sed "s/^/${f} /" | grep -v ' 0$'
  done
  return 0
}

scope_permissions() {
  local out row k flag got status
  box_new permissions
  box_env_file ZAI_CODING_API_KEY=fake-zai XAI_API_KEY=fake-xai AZURE_OPENAI_API_KEY=fake-azure \
    AZURE_OPENAI_RESOURCE=res AZURE_OPENAI_MODEL_DAILY=dep
  # kind | the CLI's own autonomy flag (providers.toml, contract §2.1)
  local -a table=(
    "claude|--dangerously-skip-permissions" "claude-glm|--dangerously-skip-permissions"
    "codex|--dangerously-bypass-approvals-and-sandbox" "codex-glm|--dangerously-bypass-approvals-and-sandbox"
    "codex-azure|--dangerously-bypass-approvals-and-sandbox" "codex-xai|--dangerously-bypass-approvals-and-sandbox"
    "cursor|--force"
    "opencode|--auto" "opencode-glm|--auto" "opencode-azure|--auto" "opencode-xai|--auto"
    "pi|--approve" "pi-glm|--approve" "pi-azure|--approve" "pi-xai|--approve"
    "cline|--yolo" "cline-azure|--yolo" "cline-xai|--yolo"
    "grok|--always-approve"
  )
  for row in "${table[@]}"; do
    k="${row%%|*}"; flag="${row#*|}"
    ak_split -- "${k}"
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k}: exactly ${flag} by default" "${got}" "${flag} 1"
    ak_split -- "${k}" --auto
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} --auto: exactly ${flag} (explicit, same as the default)" "${got}" "${flag} 1"
    ak_split -- "${k}" --ask
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} --ask: no autonomy flag" "${got}" ""
    ak_split AGENTKIT_PERMISSIONS=ask -- "${k}"
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} with AGENTKIT_PERMISSIONS=ask: no autonomy flag" "${got}" ""
  done

  # Position: --ask / --auto may sit before or after the profile and the session flag.
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude @2 -c)"
  expect_eq "ak claude @2 -c (the default adds the flag)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  expect_line "the profile applies" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude --ask @2 -c)"
  expect_eq "ak claude --ask @2 -c" "$(argv_of "${out}")" "--continue"
  expect_line "the profile still applies after --ask" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude @2 -c --ask)"
  expect_eq "ak claude @2 -c --ask" "$(argv_of "${out}")" "--continue"
  out="$(ak -- claude --auto @2 -c)"
  expect_eq "ak claude --auto @2 -c (explicit)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  out="$(ak -- claude --ask -- --auto)"
  expect_eq "after --, --auto is the CLI's argument" "$(argv_of "${out}")" "--auto"
  out="$(ak -- claude --ask fix --auto)"
  expect_eq "--auto after a CLI argument is the CLI's" "$(argv_of "${out}")" "fix|--auto"
  out="$(ak -- claude --ask --auto)"; status=$?
  expect_eq "--ask with --auto is a usage error" "${status}" 2
  expect_has "the contradiction is explained" "${out}" "--ask and --auto contradict each other"

  # The flag wins over the environment; the environment wins over the default.
  out="$(ak AGENTKIT_PERMISSIONS=ask -- codex --auto)"
  expect_eq "--auto overrides AGENTKIT_PERMISSIONS=ask" "$(argv_of "${out}")" "--dangerously-bypass-approvals-and-sandbox"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- codex --ask)"
  expect_eq "--ask overrides AGENTKIT_PERMISSIONS=auto" "$(argv_of "${out}")" ""
  out="$(ak AGENTKIT_PERMISSIONS=ASK -- codex)"
  expect_eq "AGENTKIT_PERMISSIONS is case-insensitive" "$(argv_of "${out}")" ""
  out="$(ak AGENTKIT_PERMISSIONS=yolo -- codex)"; status=$?
  expect_eq "an invalid AGENTKIT_PERMISSIONS is a usage error" "${status}" 2
  expect_has "the invalid value is explained" "${out}" "AGENTKIT_PERMISSIONS must be 'ask' or 'auto'"
  expect_eq "an invalid AGENTKIT_PERMISSIONS launches nothing" "$(grep -c '^CLI=' <<<"${out}")" 0
  box_env_file AGENTKIT_PERMISSIONS=ask
  out="$(ak -- grok)"
  expect_eq "AGENTKIT_PERMISSIONS=ask in the env file opts out" "$(argv_of "${out}")" ""
  box_env_file ZAI_CODING_API_KEY=fake-zai

  # The opt-out is inherited by what the agent starts; autonomy is not exported.
  out="$(ak AGENTKIT_PERMISSIONS=ask -- claude)"
  expect_line "an opted-out launch passes AGENTKIT_PERMISSIONS=ask on" "${out}" "AGENTKIT_PERMISSIONS=ask"
  out="$(ak -- claude --ask)"
  expect_line "--ask passes AGENTKIT_PERMISSIONS=ask on (a nested ak asks too)" "${out}" "AGENTKIT_PERMISSIONS=ask"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- claude)"
  expect_line "an autonomous launch does not export AGENTKIT_PERMISSIONS" "${out}" "AGENTKIT_PERMISSIONS="

  # Listing modes never carry an autonomy flag.
  out="$(ak -- cursor -l)"
  expect_eq "cursor -l stays a plain listing" "$(argv_of "${out}")" "ls"
  out="$(ak -- cline -r)"
  expect_eq "cline -r stays a plain history" "$(argv_of "${out}")" "history"

  # The flags exist only as data: no code path spells one.
  if grep -rnE -- '--dangerously|--yolo|--always-approve|"--force"|"--approve"' "${ROOT}/lib" "${ROOT}/bin" >/dev/null; then
    fail "an autonomy flag is spelled in lib/ or bin/ code"
  else
    pass "autonomy flags live only in providers.toml (auto = …)"
  fi
  check "every CLI declares its autonomy flag" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
m = kinds.load()
want = {"claude": ["--dangerously-skip-permissions"], "codex": ["--dangerously-bypass-approvals-and-sandbox"],
        "cursor": ["--force"], "opencode": ["--auto"], "pi": ["--approve"], "cline": ["--yolo"], "grok": ["--always-approve"]}
assert {c: m.clis[c]["auto"] for c in m.clis} == want' "${ROOT}"
}
