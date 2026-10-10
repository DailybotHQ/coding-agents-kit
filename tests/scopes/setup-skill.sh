# shellcheck shell=bash
# The agentkit-setup skill (skills/agentkit-setup/): form, marketplace rules,
# every command it teaches, and the executable-documentation scenarios.
# Checks are added with the skill.

scope_setup_skill() {
  check "setup-skill: the scope is registered" test -f "${ROOT}/tests/scopes/setup-skill.sh"
}
