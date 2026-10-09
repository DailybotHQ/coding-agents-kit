# shellcheck shell=bash
# `ak run`: the frozen per-CLI mapping, exit codes, the JSON envelope,
# process-tree kill on timeout and cancellation.

run_box() {
  box_new "$1"
  printf '{"oauthAccount":{"emailAddress":"x"}}\n' > "${BOX}/home/.claude.json"
  mkdir -p "${BOX}/home/.codex" "${BOX}/home/.grok" "${BOX}/proj"
  printf '{}\n' > "${BOX}/home/.codex/auth.json"
  printf '{}\n' > "${BOX}/home/.grok/auth.json"
  box_env_file ZAI_CODING_API_KEY=planted-zai-run AZURE_OPENAI_API_KEY=planted-azure-run AZURE_OPENAI_RESOURCE=res \
    AZURE_OPENAI_MODEL_DAILY=dep XAI_API_KEY=planted-xai-run
}

# The argv of the last record in $BOX/log, joined by |.
logged_argv() {
  awk 'BEGIN{r=""} /^---$/{last=r; r=""; next} {r=r $0 "\n"} END{printf "%s", last}' "${BOX}/log" | sed -n 's/^ARG=//p' | paste -sd '|' -
}

logged_field() {
  awk 'BEGIN{r=""} /^---$/{last=r; r=""; next} {r=r $0 "\n"} END{printf "%s", last}' "${BOX}/log" | sed -n "s/^$1=//p"
}

# run_json <VAR=value...> -- <ak run args...>: envelope in $BOX/out, status returned.
envelope_field() {
  json_get "${BOX}/out" "$1"
}

scope_run() {
  local row k want status out pid child p
  run_box run
  p="${BOX}/proj"

  # --- the frozen mapping, text and json, per kind ------------------------------
  local -a table=(
    "claude|text|-p|do it"
    "claude|json|-p|do it|--output-format|json"
    "codex|text|exec|-C|@P|do it"
    "codex|json|exec|--json|-C|@P|do it"
    "cursor|text|-p|do it|--trust"
    "cursor|json|-p|do it|--output-format|json|--trust"
    "opencode|text|run|do it"
    "opencode|json|run|--format|json|do it"
    "pi|text|-p|do it"
    "pi|json|-p|do it|--mode|json"
    "cline|text|do it|-c|@P"
    "cline|json|do it|--json|-c|@P"
    "grok|text|-p|do it|--cwd|@P"
    "grok|json|-p|do it|--output-format|json|--cwd|@P"
  )
  for row in "${table[@]}"; do
    k="${row%%|*}"; row="${row#*|}"
    local fmt="${row%%|*}"
    want="${row#*|}"
    want="${want//@P/${p}}"
    rm -f "${BOX}/log"
    ak_split FAKE_LOG="${BOX}/log" FAKE_MODE=headless -- run "${k}" --cwd "${p}" --output-format "${fmt}" -- "do it"
    status=$?
    expect_eq "ak run ${k} (${fmt}) -> ${k} ${want//|/ }" "${status}:$(logged_argv)" "0:${want}"
  done
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run cline --cwd "${p}" --timeout 30 -- "x"
  expect_eq "ak run cline --timeout passes -t" "$(logged_argv)" "x|-c|${p}|-t|30"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run codex-azure --cwd "${p}" --output-format json -- "x"
  expect_eq "provider kinds add their arguments (codex-azure)" "$(logged_argv)" "exec|-p|azure|--json|-C|${p}|x"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run claude-glm -- "x"
  expect_eq "claude-glm runs with Z.AI's base URL" "$(logged_field ANTHROPIC_BASE_URL)" "https://api.z.ai/api/anthropic"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run claude --cwd "${p}" -- "x"
  expect_eq "the CLI runs in --cwd" "$(logged_field CWD)" "${p}"
  rm -f "${BOX}/log"
  BOX_CWD="${BOX}/work" ak_split FAKE_LOG="${BOX}/log" -- run claude -- "x"
  expect_eq "without --cwd the CLI runs in the current directory" "$(logged_field CWD)" "${BOX}/work"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run claude -- fix the "quoted \"bug\""
  expect_eq "the prompt is one argument (words after -- joined)" "$(logged_argv)" '-p|fix the quoted "bug"'
  rm -f "${BOX}/log"
  printf 'from stdin\nsecond line' > "${BOX}/prompt.txt"
  ( cd "${BOX}/work" && env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" TMPDIR="${BOX}/tmp" FAKE_LOG="${BOX}/log" \
      bash "${ROOT}/bin/ak" run pi -- - <"${BOX}/prompt.txt" >/dev/null 2>&1 )
  expect_eq "-- - reads the prompt from stdin" "$(logged_argv)" "-p|from stdin"

  # --- permissions in headless runs -----------------------------------------------
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run codex --cwd "${p}" -- "x"
  expect_eq "ak run adds no autonomy flag by default" "$(logged_argv)" "exec|-C|${p}|x"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" -- run codex --auto --cwd "${p}" -- "x"
  expect_eq "ak run --auto adds the flag for this run" "$(logged_argv)" "exec|-C|${p}|--dangerously-bypass-approvals-and-sandbox|x"
  rm -f "${BOX}/log"
  ak_split FAKE_LOG="${BOX}/log" AGENTKIT_PERMISSIONS=auto -- run grok --cwd "${p}" -- "x"
  expect_eq "AGENTKIT_PERMISSIONS=auto applies to ak run" "$(logged_argv)" "-p|x|--cwd|${p}|--always-approve"
  expect_eq "the run's CLI does not inherit AGENTKIT_PERMISSIONS" "$(logged_field AGENTKIT_PERMISSIONS)" ""

  # --- the JSON envelope -----------------------------------------------------------
  for k in claude codex cursor opencode pi cline grok; do
    ak_split FAKE_MODE=headless FAKE_RESULT="answer from ${k}" -- run "${k}" --cwd "${p}" --output-format json -- "q"
    status=$?
    if [[ "${status}" -eq 0 && "$(wc -l < "${BOX}/out" | tr -d ' ')" == 1 ]] \
        && [[ "$(envelope_field 'd["result_text"]')" == "answer from ${k}" ]]; then
      pass "ak run ${k} --output-format json: one object, result_text extracted"
    else
      fail "ak run ${k} json (exit ${status}): $(cat "${BOX}/out")"
    fi
  done
  ak_split FAKE_MODE=headless FAKE_RESULT="ok" FAKE_STDERR="cli-progress-line" -- run claude --cwd "${p}" --output-format json -- "q"
  expect_eq "the envelope has exactly the contract's fields" \
    "$(envelope_field 'sorted(d)')" '["cli_exit", "cwd", "duration_s", "exit", "interface", "kind", "profile", "result_text", "truncated"]'
  expect_eq "envelope values" "$(envelope_field '[d["interface"], d["kind"], d["profile"], d["cwd"], d["exit"], d["cli_exit"], d["truncated"]]')" \
    "[1, \"claude\", \"@default\", \"${p}\", 0, 0, false]"
  expect_eq "duration_s is a non-negative number" "$(envelope_field 'isinstance(d["duration_s"], (int, float)) and d["duration_s"] >= 0')" true
  expect_has "the CLI's own output (transcript) goes to stderr" "$(cat "${BOX}/err")" '"result":"ok"'
  expect_has "the CLI's stderr reaches stderr" "$(cat "${BOX}/err")" "cli-progress-line"
  ak_split FAKE_MODE=headless FAKE_RESULT="$(printf 'x%.0s' $(seq 1 70000))" -- run claude --output-format json -- "q"
  expect_eq "a result over 64 KiB is cut and marked truncated" "$(envelope_field '[len(d["result_text"]), d["truncated"]]')" "[65536, true]"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/work"
  printf '{"oauthAccount":{}}\n' > "${BOX}/home/.local/share/agentkit/profiles/claude/work/.claude.json"
  ak_split FAKE_MODE=headless -- run claude @work --output-format json -- "q"
  expect_eq "the envelope names the profile" "$(envelope_field 'd["profile"]')" "@work"

  # --- exit codes ---------------------------------------------------------------------
  ak_split FAKE_MODE=headless FAKE_EXIT=9 -- run claude --output-format json -- "q"; status=$?
  expect_eq "exit 1 when the CLI exits non-zero (cli_exit keeps its code)" "${status}:$(envelope_field 'd["cli_exit"]')" "1:9"
  ak_split FAKE_MODE=headless FAKE_IS_ERROR=1 -- run claude --output-format json -- "q"; status=$?
  expect_eq "exit 1 when the CLI reports an error in its JSON" "${status}:$(envelope_field 'd["exit"]')" "1:1"
  ak_split FAKE_MODE=headless FAKE_IS_ERROR=1 -- run codex --output-format json -- "q"; status=$?
  expect_eq "exit 1 when codex reports turn.failed" "${status}" 1
  ak_split FAKE_EXIT=4 -- run claude -- "q"; status=$?
  expect_eq "text mode: a failing CLI is exit 1" "${status}" 1
  for args in "claude" "claude -- " "claude --output-format yaml -- x" "claude --timeout soon -- x" "claude --bogus -- x" \
      "claude --cwd /nonexistent/dir -- x" "nope -- x" ""; do
    # shellcheck disable=SC2086
    ak_split -- run ${args}; status=$?
    expect_eq "usage error (exit 2): ak run ${args}" "${status}" 2
  done
  ak_split -- run claude --output-format json --bogus -- x; status=$?
  expect_eq "a usage error with --output-format json still prints one envelope" \
    "${status}:$(envelope_field '[d["exit"], d["cli_exit"], "error" in d]')" '2:[2, null, true]'
  box_new run-missing claude
  ak_split -- run codex --output-format json -- x; status=$?
  expect_eq "exit 3 when the CLI is not installed (envelope says so)" "${status}:$(envelope_field 'd["exit"]')" "3:3"
  run_box run
  rm -f "${BOX}/home/.claude.json"
  ak_split -- run claude -- x; status=$?
  expect_eq "exit 3 when the CLI is not logged in" "${status}" 3
  expect_has "the login hint names how to log in" "$(cat "${BOX}/err")" "not logged in for @default"
  ak_split -- run claude @ghost -- x; status=$?
  expect_eq "exit 3 when the profile does not exist" "${status}" 3
  ak_split AGENTKIT_ASSUME_TTY=1 -- run claude @ghost -- x; status=$?
  if [[ "${status}" -eq 3 && ! -e "${BOX}/home/.local/share/agentkit/profiles/claude/ghost" ]]; then
    pass "ak run never asks to create a profile, even at a terminal"
  else fail "ak run created or asked for a profile (exit ${status})"; fi
  box_new run-nokey
  ak_split -- run claude-glm -- x; status=$?
  expect_eq "exit 3 when the provider key is missing" "${status}" 3
  ak_split -- run cline-xai --output-format json -- x; status=$?
  expect_has "the missing-key envelope names the variable" "$(envelope_field 'd["error"]')" "XAI_API_KEY"
  run_box run

  # --- timeout and cancellation kill the whole process tree ------------------------------
  ak_split FAKE_SLEEP=30 FAKE_CHILD_PID="${BOX}/child.pid" -- run claude --timeout 1 --output-format json -- x; status=$?
  child="$(cat "${BOX}/child.pid" 2>/dev/null)"
  expect_eq "exit 4 on timeout (envelope too)" "${status}:$(envelope_field 'd["exit"]')" "4:4"
  sleep 0.3
  if [[ -n "${child}" ]] && ! kill -0 "${child}" 2>/dev/null; then pass "timeout kills the CLI's children too"; else fail "a grandchild survived the timeout (pid ${child})"; fi
  local t0 t1
  t0="$(date +%s)"
  ( cd "${BOX}/work" && exec env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" TMPDIR="${BOX}/tmp" FAKE_SLEEP=30 \
      FAKE_CHILD_PID="${BOX}/child2.pid" bash "${ROOT}/bin/ak" run grok --output-format json -- x \
      </dev/null >"${BOX}/out" 2>"${BOX}/err" ) &
  pid=$!
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do [[ -s "${BOX}/child2.pid" ]] && break; sleep 0.2; done
  kill -TERM "${pid}"
  wait "${pid}"; status=$?
  t1="$(date +%s)"
  child="$(cat "${BOX}/child2.pid" 2>/dev/null)"
  expect_eq "exit 5 when ak run receives SIGTERM (envelope too)" "${status}:$(envelope_field 'd["exit"]')" "5:5"
  sleep 0.3
  if [[ -n "${child}" ]] && ! kill -0 "${child}" 2>/dev/null; then pass "cancellation kills the CLI's children too"; else fail "a grandchild survived cancellation (pid ${child})"; fi
  expect_eq "cancellation is prompt (well under the CLI's 30 s)" "$(( t1 - t0 < 10 ))" 1

  # --- no secret in what ak run prints ---------------------------------------------------
  run_box run
  ak_split FAKE_MODE=headless -- run claude-glm --output-format json -- x
  out="$(cat "${BOX}/out")"
  expect_lacks "the envelope never carries a key value" "${out}" "planted-zai-run"
  ak_split FAKE_MODE=headless -- run cline-xai --output-format json -- x
  expect_lacks "cline's auth step never reaches stdout" "$(cat "${BOX}/out")" "planted-xai-run"
}
