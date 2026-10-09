# shellcheck shell=bash
# Permission posture: pass-through by default, the CLI's own autonomy flag
# only on an explicit opt-in (--auto or AGENTKIT_PERMISSIONS=auto).

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
    expect_eq "${k}: no autonomy flag by default" "${got}" ""
    ak_split -- "${k}" --auto
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} --auto: exactly ${flag}" "${got}" "${flag} 1"
    ak_split AGENTKIT_PERMISSIONS=auto -- "${k}"
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} with AGENTKIT_PERMISSIONS=auto: exactly ${flag}" "${got}" "${flag} 1"
  done

  # Position: --auto may sit before or after the profile and the session flag.
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude --auto @2 -c)"
  expect_eq "ak claude --auto @2 -c (the classic alias form)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  expect_line "the profile still applies after --auto" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude @2 -c --auto)"
  expect_eq "ak claude @2 -c --auto" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  out="$(ak -- claude -- --auto)"
  expect_eq "after --, --auto is the CLI's argument" "$(argv_of "${out}")" "--auto"
  out="$(ak -- claude fix --auto)"
  expect_eq "--auto after a CLI argument is the CLI's" "$(argv_of "${out}")" "fix|--auto"

  # Explicit ask, the env file, invalid values.
  out="$(ak AGENTKIT_PERMISSIONS=ask -- codex)"
  expect_eq "AGENTKIT_PERMISSIONS=ask adds nothing" "$(argv_of "${out}")" ""
  out="$(ak AGENTKIT_PERMISSIONS=AUTO -- codex)"
  expect_eq "AGENTKIT_PERMISSIONS is case-insensitive" "$(argv_of "${out}")" "--dangerously-bypass-approvals-and-sandbox"
  out="$(ak AGENTKIT_PERMISSIONS=yolo -- codex)"; status=$?
  expect_eq "an invalid AGENTKIT_PERMISSIONS is a usage error" "${status}" 2
  expect_has "the invalid value is explained" "${out}" "AGENTKIT_PERMISSIONS must be 'ask' or 'auto'"
  expect_eq "an invalid AGENTKIT_PERMISSIONS launches nothing" "$(grep -c '^CLI=' <<<"${out}")" 0
  box_env_file AGENTKIT_PERMISSIONS=auto
  out="$(ak -- grok)"
  expect_eq "AGENTKIT_PERMISSIONS=auto in the env file opts in" "$(argv_of "${out}")" "--always-approve"
  box_env_file ZAI_CODING_API_KEY=fake-zai

  # Autonomy is never inherited by what the agent starts.
  out="$(ak AGENTKIT_PERMISSIONS=auto -- claude)"
  expect_line "AGENTKIT_PERMISSIONS is not passed to the CLI" "${out}" "AGENTKIT_PERMISSIONS="

  # Listing modes never carry an autonomy flag, even with --auto.
  out="$(ak -- cursor --auto -l)"
  expect_eq "cursor --auto -l stays a plain listing" "$(argv_of "${out}")" "ls"
  out="$(ak -- cline --auto -r)"
  expect_eq "cline --auto -r stays a plain history" "$(argv_of "${out}")" "history"

  # The flags exist only as data: no code path can add one by default.
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
