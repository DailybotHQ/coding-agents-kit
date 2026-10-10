# shellcheck shell=bash
# The agentkit-setup skill (skills/agentkit-setup/): form, marketplace rules,
# every command it teaches, its consent gates, and `ak --skill setup`. The
# executable-documentation scenarios are added with the end-to-end task.

scope_setup_skill() {
  local out status dest
  check "setup-skill: skills/agentkit-setup/SKILL.md exists" test -f "${ROOT}/skills/agentkit-setup/SKILL.md"
  py_checks skill_checks.py "${ROOT}" agentkit-setup

  box_new setup-skill
  ak_split -- --skill setup; status=$?
  expect_eq "setup-skill: ak --skill setup exits 0" "${status}" 0
  check "setup-skill: ak --skill setup prints SKILL.md byte for byte" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit-setup/SKILL.md"
  ak_split -- --skill; status=$?
  check "setup-skill: ak --skill still prints the agentkit skill" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit/SKILL.md"
  ak_split -- --skill nope; status=$?
  expect_eq "setup-skill: an unknown skill name exits 2" "${status}" 2
  box_run -- bash "${ROOT}/install.sh" --no-rc >/dev/null
  dest="${BOX}/home/.local/share/agentkit"
  check "setup-skill: install.sh ships the skill and its references" test -f "${dest}/skills/agentkit-setup/references/container.md"
  out="$(box_run -- "${dest}/bin/ak" --skill setup)"
  expect_has "setup-skill: the installed ak --skill setup prints the installed copy" "${out}" "name: agentkit-setup"
}
