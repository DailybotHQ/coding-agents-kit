# shellcheck shell=bash
# `ak pick --kinds` (lib/pick.py): the cross-kind priority pick for daemons
# (pick-v2) — the first kind of the list with a qualifying account wins, the
# JSON carries the exact launch argv, and nothing prompts. Runs through the
# real launcher in a sandbox home against the loopback fake usage endpoint,
# with several Claude accounts whose numbers differ (the pick.sh setup), plus
# a kind with no login (claude-glm) to exercise the fall-through.

scope_pick_kinds() {
  local doc status out schema="${ROOT}/docs/schema/pick-v2.json"
  box_new pick claude
  local t0="planted-pick-default-0x1" t1="planted-pick-work-0x1" t2="planted-pick-two-0x1" name tok dir
  for name in default work 2; do
    case "${name}" in default) tok="${t0}"; dir="${BOX}/home/.claude" ;; work) tok="${t1}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/work" ;;
      2) tok="${t2}"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/2" ;; esac
    mkdir -p "${dir}"
    printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${tok}" > "${dir}/.credentials.json"
  done
  "${AK_PY}" - "${BOX}/routes.json" "${t0}" "${t1}" "${t2}" <<'PY'
import json, sys
path, t0, t1, t2 = sys.argv[1:]
def c(a, b):
    return {"json": {"five_hour": {"utilization": a, "resets_at": "2099-01-01T00:00:00Z"}, "seven_day": {"utilization": b, "resets_at": "2099-01-05T00:00:00Z"}}}
json.dump({"/claude": {"by_bearer": {t0: c(10, 85), t1: c(55, 20), t2: c(91, 30)}}}, open(path, "w"))
PY
  usage_server_start "${BOX}/routes.json"
  local url="AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://127.0.0.1:${USAGE_PORT}/claude"

  # The fall-through: claude-glm has no login in the sandbox, so the SECOND
  # kind of the list wins and priority_index says so.
  ak_split "${url}" -- pick --kinds claude-glm,claude --json; status=$?
  doc="${BOX}/kinds.json"; cp "${BOX}/out" "${doc}"
  expect_eq "pick kinds: exit 0 when a later kind qualifies" "${status}" 0
  out="$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")"
  expect_eq "pick kinds: --json matches docs/schema/pick-v2.json" "${out}" "valid"
  expect_eq "pick kinds: the winner is the second kind of the list" "$(json_get "${doc}" '[d["kind"], d["priority_index"], d["profile"]]')" '["claude", 1, "@work"]'
  expect_eq "pick kinds: launch argv is the exact interactive command" "$(json_get "${doc}" 'd["launch"]["argv"]')" '["ak", "claude", "@work"]'
  expect_eq "pick kinds: env_names empty on the default path" "$(json_get "${doc}" 'd["launch"]["env_names"]')" '[]'
  expect_eq "pick kinds: model null without --model-for" "$(json_get "${doc}" 'd["model"]')" 'null'

  # A model for the winning kind rides the launch argv.
  ak_split "${url}" -- pick --kinds claude-glm,claude --model-for claude=sonnet --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "pick kinds: --model-for sets the model" "$(json_get "${doc}" 'd["model"]')" 'sonnet'
  expect_eq "pick kinds: the model rides the launch argv after --" "$(json_get "${doc}" 'd["launch"]["argv"]')" '["ak", "claude", "@work", "--", "--model", "sonnet"]'

  # Human output stays the single-kind line.
  ak_split "${url}" -- pick --kinds claude-glm,claude; status=$?
  expect_eq "pick kinds: human line, exit 0" "${status}" 0
  expect_has "pick kinds: the human line names the account" "$(cat "${BOX}/out")" "claude @work"

  # Nothing qualifies: exit 1, every kind's reason, the soonest reset.
  ak_split "${url}" -- pick --kinds claude-glm,claude --need 5h:95; status=$?
  expect_eq "pick kinds: none qualifies exits 1" "${status}" 1
  expect_has "pick kinds: the refusal names both kinds" "$(cat "${BOX}/err")" "across claude-glm,claude"
  expect_has "pick kinds: the refusal names the soonest reset" "$(cat "${BOX}/err")" "Soonest reset"

  # Parse contract: mutually exclusive forms and bad --model-for.
  ak_split "${url}" -- pick --kinds claude,claude; status=$?
  expect_eq "pick kinds: duplicate kinds are a usage error" "${status}" 2
  ak_split "${url}" -- pick --kinds claude claude; status=$?
  expect_eq "pick kinds: --kinds with a positional target is a usage error" "${status}" 2
  ak_split "${url}" -- pick claude --model-for claude=sonnet; status=$?
  expect_eq "pick kinds: --model-for without --kinds is a usage error" "${status}" 2
  ak_split "${url}" -- pick --kinds claude --model-for codex=x; status=$?
  expect_eq "pick kinds: --model-for naming a kind outside the list is a usage error" "${status}" 2
  ak_split "${url}" -- pick --kinds claude @work; status=$?
  expect_eq "pick kinds: a pinned profile with --kinds is a usage error" "${status}" 2
}
