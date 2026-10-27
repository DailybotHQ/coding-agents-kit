# shellcheck shell=bash
# Resume through ak after a Herdr restart (lib/restore.py): a launch inside a
# Herdr pane reports `ak <kind> @<profile> --resume <id>` for the session id
# Herdr recorded; outside Herdr, or with AGENTKIT_HERDR_RESUME=0, it does not.
# `ak last` goes back to the last launch of a directory in any terminal.
# The logic itself is in tests/py/restore_checks.py (also run on Windows).

# restore_state <agent> <id> — what the fake `herdr pane get` shows.
restore_state() {
  printf '{"id":"cli:pane:get","result":{"pane":{"pane_id":"w1:p1","agent_session":{"source":"herdr:%s","agent":"%s","kind":"id","value":"%s"}}}}\n' \
    "$1" "$1" "$2" > "${BOX}/herdr-state.json"
}

# restore_wait — past the watcher's last read: it reads every 0.1 s and
# exits at the first read after the CLI is gone.
restore_wait() {
  "${AK_PY}" -c 'import time; time.sleep(0.8)'
}

restore_launch() {
  rm -f "${BOX}/herdr.log"
  : > "${BOX}/herdr.log"
  ak HERDR_FAKE_LOG="${BOX}/herdr.log" HERDR_FAKE_STATE="${BOX}/herdr-state.json" HERDR_PANE_ID=w1:p1 \
    HERDR_SOCKET_PATH="${BOX}/herdr.sock" AGENTKIT_HERDR_RESUME_INTERVAL=0.1 FAKE_SLEEP=1 "$@"
  restore_wait
}

scope_restore() {
  local out log status
  box_new restore claude grok
  cp "${ROOT}/tests/fakes-host/herdr/herdr" "${BOX}/bin/herdr"
  box_env_file XAI_API_KEY=fake-xai-key CLAUDE_CODE_OAUTH_TOKEN_WORK=fake-claude-token
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/work"

  py_checks restore_checks.py

  restore_state claude 11111111-aaaa
  out="$(restore_launch HERDR_ENV=1 -- claude @work)"
  log="$(cat "${BOX}/herdr.log")"
  expect_has "the CLI still starts (its record is on stdout)" "${out}" "CLI=claude"
  expect_has "the watcher reads the pane" "${log}" "CALL pane get w1:p1"
  expect_has "the session is reported with ak's resume command" "${log}" \
    "--agent claude --seq"
  expect_has "the resume command is ak claude @work --resume <id>" "${log}" \
    "--agent-session-id 11111111-aaaa -- ak claude @work --resume 11111111-aaaa"
  expect_has "Herdr's source is kept" "${log}" "--source herdr:claude"
  expect_eq "one report for one id" "$(grep -c 'report-agent-session' <<<"${log}")" 1
  expect_lacks "no key or token reaches the watcher" "${log}" "SECRET=present"

  restore_state grok 22222222-bbbb
  log="$(restore_launch HERDR_ENV=1 AGENTKIT_PERMISSIONS=ask -- grok >/dev/null; cat "${BOX}/herdr.log")"
  expect_has "@default and the opt-out are kept explicit" "${log}" "-- ak grok @default --ask --resume 22222222-bbbb"
  expect_lacks "an API-key profile's key never reaches the watcher" "${log}" "SECRET=present"

  restore_state claude 33333333-cccc
  log="$(restore_launch -- claude @work >/dev/null; cat "${BOX}/herdr.log")"
  expect_eq "outside Herdr, Herdr is never called" "${log}" ""
  log="$(restore_launch HERDR_ENV=1 AGENTKIT_HERDR_RESUME=0 -- claude @work >/dev/null; cat "${BOX}/herdr.log")"
  expect_eq "AGENTKIT_HERDR_RESUME=0 turns it off" "${log}" ""

  restore_state codex 44444444-dddd
  log="$(restore_launch HERDR_ENV=1 -- claude @work >/dev/null; cat "${BOX}/herdr.log")"
  expect_lacks "a session of another CLI in the pane is not reported" "${log}" "report-agent-session"

  # ak last: any terminal, no Herdr.
  mkdir -p "${BOX}/work/repo-a" "${BOX}/work/repo-b" "${BOX}/work/fresh"
  BOX_CWD="${BOX}/work/repo-a" ak -- claude @work >/dev/null
  BOX_CWD="${BOX}/work/repo-b" ak AGENTKIT_PERMISSIONS=ask -- grok >/dev/null
  out="$(BOX_CWD="${BOX}/work/repo-a" ak -- last)"
  expect_eq "ak last continues the last launch of this directory" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  expect_has "in the same profile" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/work"
  expect_has "and says what it runs" "${out}" "ak: ak claude @work -c"
  out="$(BOX_CWD="${BOX}/work/repo-b" ak -- last -r)"
  expect_eq "ak last -r opens the picker, opt-out kept" "$(argv_of "${out}")" "--resume"
  expect_has "the opted-out launch stays opted out" "${out}" "AGENTKIT_PERMISSIONS=ask"
  out="$(ak -- last ls)"
  expect_has "ak last ls lists each directory" "${out}" "ak claude @work  "
  expect_has "with the opt-out" "${out}" "ak grok @default --ask  "
  out="$(BOX_CWD="${BOX}/work/fresh" ak -- last)"; status=$?
  expect_eq "a directory with no launch is a usage error" "${status}" 2
  expect_has "that points at ak last ls" "${out}" "ak last ls"
  out="$(ak -- last --bogus)"
  expect_has "an unknown argument is refused" "${out}" "usage: ak last"
  BOX_CWD="${BOX}/work/fresh" ak -- run claude @work -- "hi" >/dev/null
  expect_lacks "a headless ak run is not recorded" "$(ak -- last ls)" "/fresh"
}
