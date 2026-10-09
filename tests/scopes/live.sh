# shellcheck shell=bash
# Real CLIs, real logins: never part of the default run. A real CLI reads
# your real login and writes its session into your real HOME, so this scope
# runs only with AGENTKIT_TEST_LIVE=1 (and a list in AGENTKIT_TEST_LIVE_KINDS,
# default: every installed canonical kind). Each kind answers one tiny prompt
# through `ak run` and must return exit 0 with the expected text.

scope_live() {
  local k status out kinds_list
  if [[ "${AGENTKIT_TEST_LIVE:-}" != 1 ]]; then
    skip "live: unavailable (set AGENTKIT_TEST_LIVE=1 to run real CLIs against your real logins)"
    return 0
  fi
  kinds_list="${AGENTKIT_TEST_LIVE_KINDS:-claude codex cursor opencode pi cline grok}"
  for k in ${kinds_list}; do
    out="$(cd "${SANDBOX}" && HOME="${REAL_HOME}" PATH="${REAL_PATH}" bash "${ROOT}/bin/ak" run "${k}" \
      --timeout 180 --output-format json -- "Reply with exactly the word AGENTKIT_LIVE_OK and nothing else." 2>/dev/null)"
    status=$?
    if [[ "${status}" -eq 3 ]]; then
      skip "live ${k}: unavailable (not installed or not logged in)"
    elif [[ "${status}" -eq 0 && "${out}" == *AGENTKIT_LIVE_OK* ]]; then
      pass "live ${k}: ak run answered through the real CLI"
    else
      fail "live ${k}: exit ${status}: ${out:0:300}"
    fi
  done
}
