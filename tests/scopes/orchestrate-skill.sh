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
