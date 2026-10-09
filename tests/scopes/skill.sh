# shellcheck shell=bash
# skills/agentkit: valid frontmatter, marketplace rules, and `ak --skill`.

scope_skill() {
  local out status dest
  check "skills/agentkit/SKILL.md exists" test -f "${ROOT}/skills/agentkit/SKILL.md"
  py_checks skill_checks.py "${ROOT}"
  box_new skill
  ak_split -- --skill; status=$?
  expect_eq "ak --skill exits 0" "${status}" 0
  check "ak --skill prints the bundled SKILL.md byte for byte" cmp -s "${BOX}/out" "${ROOT}/skills/agentkit/SKILL.md"
  box_run -- bash "${ROOT}/install.sh" --no-rc >/dev/null
  dest="${BOX}/home/.local/share/agentkit"
  check "install.sh ships the skill" test -f "${dest}/skills/agentkit/SKILL.md"
  out="$(box_run -- "${dest}/bin/ak" --skill)"
  expect_has "the installed ak --skill prints the installed copy" "${out}" "name: agentkit"
  out="$(box_run -- "${dest}/bin/agentkit" --skill | head -2)"
  expect_has "agentkit --skill works too" "${out}" "name: agentkit"
}
