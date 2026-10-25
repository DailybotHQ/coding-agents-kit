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

  setup_skill_scenarios
}

# Executable documentation: the commands the skill teaches are extracted and run
# in sandboxes (tests/py/skill_scenarios.py); then three deliberate drifts of the
# words prove the suite notices when the skill and the tool disagree.
setup_skill_scenarios() {
  local drift copy out status
  py_checks skill_scenarios.py "${ROOT}"
  for drift in "install.sh --no-rc|install.sh --no-rcc" "--branch v1.1.0|--branch v9.9.9" "setup verify --json|setup verify --jsno"; do
    copy="${SANDBOX}/skill-drift"
    rm -rf "${copy}"
    cp -R "${ROOT}/skills/agentkit-setup" "${copy}"
    sed -e "s|${drift%%|*}|${drift##*|}|g" "${copy}/SKILL.md" > "${copy}/SKILL.md.new" && mv "${copy}/SKILL.md.new" "${copy}/SKILL.md"
    for f in "${copy}"/references/*.md; do
      sed -e "s|${drift%%|*}|${drift##*|}|g" "${f}" > "${f}.new" && mv "${f}.new" "${f}"
    done
    out="$("${AK_PY}" "${ROOT}/tests/py/skill_scenarios.py" "${ROOT}" --skill-dir "${copy}" 2>&1)"; status=$?
    expect_eq "setup-skill scenario mutation: a drifted '${drift%%|*}' makes the executable documentation fail" \
      "${status}:$([[ ${out} == *"FAIL "* ]] && echo failed)" "1:failed"
  done
}

