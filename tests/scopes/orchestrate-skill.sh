# shellcheck shell=bash
# The agentkit-orchestrate skill (skills/agentkit-orchestrate/): form,
# marketplace rules, every command it teaches, its safety rules, and
# `ak --skill orchestrate`. The executable scenarios (the commands the skill
# teaches, run against fake accounts) are in orchestrate_skill_scenarios.

scope_orchestrate_skill() {
  local out status dest
  check "orchestrate-skill form: skills/agentkit-orchestrate/SKILL.md exists" test -f "${ROOT}/skills/agentkit-orchestrate/SKILL.md"
  py_checks skill_checks.py "${ROOT}" agentkit-orchestrate

  box_new orchestrate-skill
  ak_split -- --skill orchestrate; status=$?
  expect_eq "orchestrate-skill form: ak --skill orchestrate exits 0" "${status}" 0
  check "orchestrate-skill form: ak --skill orchestrate prints SKILL.md byte for byte" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit-orchestrate/SKILL.md"
  ak_split -- --skill agentkit-orchestrate; status=$?
  check "orchestrate-skill form: the long name works too" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit-orchestrate/SKILL.md"
  ak_split -- --skill; status=$?
  check "orchestrate-skill form: ak --skill still prints the agentkit skill" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit/SKILL.md"
  box_run -- bash "${ROOT}/install.sh" --no-rc >/dev/null
  dest="${BOX}/home/.local/share/agentkit"
  check "orchestrate-skill form: install.sh ships the skill and its references" \
    test -f "${dest}/skills/agentkit-orchestrate/references/patterns.md"
  out="$(box_run -- "${dest}/bin/ak" --skill orchestrate)"
  expect_has "orchestrate-skill form: the installed ak --skill orchestrate prints the installed copy" "${out}" "name: agentkit-orchestrate"

  if declare -F orchestrate_skill_scenarios >/dev/null; then
    orchestrate_skill_scenarios
  fi
}

# Executable documentation: the loop the skill teaches runs against fake
# accounts (tests/py/orchestrate_scenarios.py); then deliberate drifts of the
# words prove the suite notices when the skill and the tool disagree.
orchestrate_skill_scenarios() {
  local drift copy out
  py_checks orchestrate_scenarios.py "${ROOT}"
  for drift in "--count 3 --json|--cnt 3 --json" "claude @work2 --cwd ../wt-api|claude @work9 --cwd ../wt-api" "--model fable|--model fabel"; do
    copy="${SANDBOX}/orchestrate-drift"
    rm -rf "${copy}"
    cp -R "${ROOT}/skills/agentkit-orchestrate" "${copy}"
    sed -e "s|${drift%%|*}|${drift##*|}|g" "${copy}/SKILL.md" > "${copy}/SKILL.md.new" && mv "${copy}/SKILL.md.new" "${copy}/SKILL.md"
    out="$(cd "${SANDBOX}" && env -i HOME="${HOME}" PATH="${BASE_PATH}" "${AK_PY}" "${ROOT}/tests/py/orchestrate_scenarios.py" "${ROOT}" --skill-dir "${copy}" 2>&1)"
    expect_has "orchestrate-skill scenario: a drift of the words (${drift%%|*}) fails the scenarios" "${out}" "FAIL "
  done
}
