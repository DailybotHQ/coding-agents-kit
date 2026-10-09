# shellcheck shell=bash
# The harness itself: fakes, sandbox HOME, PATH isolation, scope dispatch.

scope_harness() {
  local c out

  for c in ${ALL_CLIS}; do
    check "fake ${c} exists and is executable" test -x "${FAKES}/${c}"
  done

  expect_eq "sandbox HOME is not the real HOME" "$([[ "${HOME}" != "${REAL_HOME}" && "${HOME}" == "${SANDBOX}"/* ]] && echo yes)" yes

  box_new harness
  out="$(box_run -- sh -c 'command -v claude')"
  expect_eq "a box resolves claude to its fake" "${out}" "${BOX}/bin/claude"
  out="$(box_run -- env)"
  expect_lacks "a box passes no real *_API_KEY into commands" "${out}" "_API_KEY="
  expect_line "a box's HOME is its own" "${out}" "HOME=${BOX}/home"

  out="$(box_run -- claude -p "two words" "--flag=x y" "")"
  expect_eq "fakes record argv with boundaries kept" "$(argv_of "${out}")" "-p|two words|--flag=x y|"
  expect_line "fakes record the argument count" "${out}" "ARGC=4"
  expect_line "fakes record the working directory" "${out}" "CWD=${BOX}/work"

  box_run FAKE_EXIT=7 -- codex >/dev/null
  expect_eq "fakes honour FAKE_EXIT" "$?" 7

  out="$(box_run ZAI_CODING_API_KEY=planted-value -- claude)"
  expect_line "fakes hide secret values unless asked" "${out}" "ZAI_CODING_API_KEY=(set)"
  out="$(box_run ZAI_CODING_API_KEY=planted-value FAKE_SHOW_SECRETS=1 -- claude)"
  expect_line "fakes show secret values when asked" "${out}" "ZAI_CODING_API_KEY=planted-value"

  box_run FAKE_LOG="${BOX}/log" -- pi a >/dev/null
  box_run FAKE_LOG="${BOX}/log" -- pi b >/dev/null
  expect_eq "FAKE_LOG keeps one record per call" "$(grep -c '^CLI=pi$' "${BOX}/log")" 2

  out="$(box_run FAKE_MODE=headless FAKE_RESULT='say "hi"' -- claude -p x --output-format json)"
  check "headless claude fake emits valid JSON" "${AK_PY}" -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["result"]=="say \"hi\""' "${out}"
  out="$(box_run FAKE_MODE=headless -- codex exec --json x)"
  check "headless codex fake emits JSON lines" "${AK_PY}" -c 'import json,sys; [json.loads(l) for l in sys.argv[1].splitlines()]' "${out}"
  out="$(box_run -- agent --help)"
  expect_has "the agent fake identifies as Cursor" "${out}" "Cursor"
  printf '[{"sessionId":"s1"}]\n' > "${BOX}/hist.json"
  out="$(box_run FAKE_CLINE_HISTORY="${BOX}/hist.json" -- cline history --json)"
  expect_eq "the cline fake serves a history fixture" "${out}" '[{"sessionId":"s1"}]'

  box_new harness-subset claude
  out="$(box_run -- sh -c 'command -v codex || echo none')"
  expect_eq "a box can hide a CLI (not installed)" "${out}" none

  out="$(bash "${ROOT}/tests/run.sh" no-such-scope 2>&1)"
  expect_eq "an unknown scope is a usage error (exit 2)" "$?" 2
  out="$(cd / && bash "${ROOT}/tests/run.sh" harness-selftest 2>&1 | tail -1)"
  expect_has "the runner works from another directory" "${out}" "failed: 0"
}
