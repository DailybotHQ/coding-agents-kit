# shellcheck shell=bash
# The dispatcher: grammar, per-CLI session flags, provider arguments, exec.

# dispatch_case "<ak args>" "<want argv joined by |>" [VAR=value...]
dispatch_case() {
  local args="$1" want="$2" out
  shift 2
  # shellcheck disable=SC2086  # args is a word list on purpose
  out="$(ak "$@" -- ${args})"
  expect_eq "ak ${args} -> ${want:-(no arguments)}" "$(argv_of "${out}")" "${want}"
}

scope_dispatch() {
  local out status row args want
  box_new dispatch
  box_posture ask  # argv grammar; the permissions scope owns the default
  printf '[{"sessionId":"sess-old","cwd":"%s","isSubagent":false,"updatedAt":"2026-10-01T00:00:00Z"},{"sessionId":"sess-new","cwd":"%s","isSubagent":false,"updatedAt":"2026-10-05T00:00:00Z"},{"sessionId":"sess-sub","cwd":"%s","isSubagent":true,"updatedAt":"2026-10-07T00:00:00Z"},{"sessionId":"sess-other","cwd":"/elsewhere","isSubagent":false,"updatedAt":"2026-10-08T00:00:00Z"}]\n' \
    "${BOX}/work" "${BOX}/work" "${BOX}/work" > "${BOX}/cline-history.json"

  # Session flags per CLI (the private kit's continue/resume table).
  local -a table=(
    "claude|"
    "claude -c|--continue"
    "claude --continue|--continue"
    "claude -r abc|--resume|abc"
    "claude --resume abc|--resume|abc"
    "claude -r|--resume"
    "claude -l|-l"
    "codex -c|resume|--last"
    "codex -l|resume|--last"
    "codex --last|resume|--last"
    "codex -r abc|resume|abc"
    "codex -r|resume|--all"
    "cursor -c|--continue"
    "cursor -r abc|--resume=abc"
    "cursor -r|--resume"
    "cursor -l|ls"
    "opencode -c|--continue"
    "opencode -r abc|--session|abc"
    "pi -c|--continue"
    "pi -r abc|--session|abc"
    "pi -r|--resume"
    "cline -c|--id|sess-new"
    "cline -r abc|--id|abc"
    "cline -r|history"
    "grok -c|--continue"
    "grok -r abc|--resume|abc"
    "grok -r|--resume"
  )
  for row in "${table[@]}"; do
    dispatch_case "${row%%|*}" "${row#*|}" FAKE_CLINE_HISTORY="${BOX}/cline-history.json"
  done

  # Only the head is the kit's; everything else reaches the CLI untouched.
  dispatch_case "claude 2" "2"
  dispatch_case "claude 2 -c" "2|-c"
  dispatch_case "claude fix -c" "fix|-c"
  dispatch_case "claude mcp list" "mcp|list"
  dispatch_case "claude -c fix the bug" "--continue|fix|the|bug"
  dispatch_case "claude -- @src/a.ts explain" "@src/a.ts|explain"
  dispatch_case "claude -- -c" "-c"
  dispatch_case "claude -r -x" "--resume|-x"
  dispatch_case "codex -c -c" "resume|--last|-c"
  out="$(ak -- claude -p "two words" "")"
  expect_eq "arguments keep their boundaries" "$(argv_of "${out}")" "-p|two words|"

  # Provider variants put their arguments where each CLI expects them.
  dispatch_case "codex-glm -c" "-p|glm|resume|--last" ZAI_CODING_API_KEY=fake-zai-one
  dispatch_case "codex-xai -r abc" "-p|xai|resume|abc" XAI_API_KEY=fake-xai-one
  dispatch_case "opencode-xai -c" "-m|xai/grok-4.3|--continue" XAI_API_KEY=fake-xai-one
  dispatch_case "opencode-glm" "-m|zai-coding-plan/glm-5.3" ZAI_CODING_API_KEY=fake-zai-one
  dispatch_case "pi-glm -r abc" "--provider|zai-glm|--model|glm-5.3|--models|zai-glm/glm-5.3,zai-glm/glm-5.3-flash|--session|abc" ZAI_CODING_API_KEY=fake-zai-one
  dispatch_case "pi-azure" "--provider|azure-foundry|--model|my-dep|--models|azure-foundry/my-dep" \
    AZURE_OPENAI_API_KEY=fake-azure-one AZURE_OPENAI_RESOURCE=res AZURE_OPENAI_MODEL_DAILY=my-dep
  out="$(ak ZAI_CODING_API_KEY=fake-zai-one -- claude-glm -c)"
  expect_line "claude-glm points Claude at Z.AI" "${out}" "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic"
  expect_line "claude-glm passes the key in its environment" "${out}" "ANTHROPIC_AUTH_TOKEN=(set)"
  expect_eq "claude-glm -c -> --continue" "$(argv_of "${out}")" "--continue"
  ak_split XAI_API_KEY=fake-xai-one FAKE_LOG="${BOX}/cline.log" FAKE_CLINE_HISTORY="${BOX}/cline-history.json" -- cline-xai -c
  expect_eq "cline-xai -c -> provider flags then the session" "$(argv_of "$(cat "${BOX}/out")")" "-P|openai|-m|grok-4.3|-k|fake-xai-one|--id|sess-new"
  expect_has "cline auth output goes to stderr, never stdout" "$(cat "${BOX}/err")" "ARG=auth"
  expect_eq "cline-xai authenticates first (one cline auth)" "$(grep -c '^ARG=auth$' "${BOX}/cline.log")" 1
  rm -f "${BOX}/cline.log"
  out="$(ak XAI_API_KEY=fake-xai-one FAKE_LOG="${BOX}/cline.log" -- cline-xai -r)"
  expect_eq "cline-xai -r lists history without auth or key" "$(argv_of "${out}")" "history"
  expect_eq "cline-xai -r runs no cline auth" "$(grep -c '^ARG=auth$' "${BOX}/cline.log")" 0

  # Refusals: one line, nothing launched.
  out="$(ak -- opencode -r)"; status=$?
  expect_has "opencode -r without an id names 'opencode session list'" "${out}" "opencode session list"
  expect_eq "opencode -r without an id is a usage error and launches nothing" "${status}:$(grep -c '^CLI=' <<<"${out}")" "2:0"
  printf '[]\n' > "${BOX}/empty-history.json"
  out="$(ak FAKE_CLINE_HISTORY="${BOX}/empty-history.json" -- cline -c)"; status=$?
  expect_has "cline -c with no session here refuses (never -c as --cwd)" "${out}" "no Cline session to continue"
  expect_eq "cline -c refusal launches nothing" "$(grep -c '^CLI=' <<<"${out}")" 0
  out="$(ak -- nope)"; status=$?
  expect_eq "an unknown kind is a usage error" "${status}" 2
  expect_has "an unknown kind lists the kinds" "${out}" "claude-glm"
  out="$(ak -- --bogus)"; status=$?
  expect_eq "an unknown option is a usage error" "${status}" 2
  out="$(ak -- claude-glm)"; status=$?
  expect_eq "a provider kind without its key exits 3" "${status}" 3
  expect_has "the missing key is named" "${out}" "ZAI_CODING_API_KEY is not set"
  out="$(ak -- codex-azure)"; status=$?
  expect_has "azure names every missing setting" "${out}" "AZURE_OPENAI_RESOURCE or AZURE_OPENAI_BASE_URL"

  # The verbs around launching.
  out="$(ak -- --version)"
  expect_eq "ak --version" "${out}" "agentkit 0.1.1 (interface 1)"
  out="$(ak)"; status=$?
  expect_eq "ak with no arguments lists the kinds" "${status}:$(grep -c '^claude-glm ' <<<"${out}")" "0:1"
  expect_has "ak with no arguments shows what is installed" "${out}" "${BOX}/bin/claude"
  out="$(ak -- --help)"
  expect_has "ak --help shows the grammar" "${out}" "ak run <kind>"
  check "bin/ak and bin/agentkit are the same script" cmp -s "${ROOT}/bin/ak" "${ROOT}/bin/agentkit"
  out="$(box_run -- bash "${ROOT}/bin/agentkit" claude -c)"
  expect_eq "agentkit dispatches like ak" "$(argv_of "${out}")" "--continue"
  ln -s "${ROOT}/bin/ak" "${BOX}/bin/ak"
  out="$(box_run -- ak codex -l)"
  expect_eq "ak works through a symlink on PATH" "$(argv_of "${out}")" "resume|--last"
  out="$(box_run -- sh -c 'echo "SHELL_PID=$$"; exec ak claude')"
  expect_eq "ak exec's the CLI (same process: Herdr sees the agent)" \
    "$(sed -n 's/^SHELL_PID=//p' <<<"${out}")" "$(sed -n 's/^PID=//p' <<<"${out}")"
  out="$(box_run -- sh -c 'cd "${HOME}" && ak claude')"
  expect_line "the CLI starts in the caller's directory" "${out}" "CWD=${BOX}/home"

  # Not installed: exit 3 and the install command, nothing launched.
  box_new dispatch-missing claude
  box_posture ask  # argv grammar; the permissions scope owns the default
  out="$(ak -- codex)"; status=$?
  expect_eq "a CLI that is not installed exits 3" "${status}" 3
  expect_has "a CLI that is not installed names ak install" "${out}" "ak install codex"

  # Cursor: a Grok-installed `agent` is not Cursor; cursor-agent is preferred.
  box_new dispatch-cursor
  box_posture ask  # argv grammar; the permissions scope owns the default
  mkdir -p "${BOX}/home/.grok/bin"
  mv "${BOX}/bin/agent" "${BOX}/home/.grok/bin/agent"
  printf '#!/bin/sh\necho "grok 1.0.0"\n' > "${BOX}/home/.grok/bin/agent"
  chmod +x "${BOX}/home/.grok/bin/agent"
  ln -s "${BOX}/home/.grok/bin/agent" "${BOX}/bin/agent"
  out="$(ak -- cursor)"; status=$?
  expect_eq "a Grok-shipped agent is not taken for Cursor" "${status}" 3
  cp "${FAKES}/agent" "${BOX}/bin/cursor-agent"
  out="$(ak -- cursor -c)"
  expect_line "cursor-agent is used when present" "${out}" "CLI=cursor-agent"

  # The env file: loaded as shell, keys reach the CLI, names never leak.
  box_new dispatch-envfile
  box_posture ask  # argv grammar; the permissions scope owns the default
  box_env_file 'ZAI_CODING_API_KEY=fake-zai-file' 'ZAI_CODING_API_KEY_2=fake-zai-two' 'echo "${UNSET_IN_ENV_FILE}" >/dev/null'
  out="$(ak FAKE_ENV_NAMES=1 -- claude-glm)"; status=$?
  expect_eq "the env file is loaded (claude-glm finds its key)" "${status}" 0
  expect_lacks "an unset variable in the env file does not abort" "${out}" "unbound variable"
  expect_lacks "per-profile keys (<KEY>_<SUFFIX>) never reach the CLI" "${out}" "ENVNAME=ZAI_CODING_API_KEY_2"
  expect_lacks "the kit's bookkeeping variable never reaches the CLI" "${out}" "ENVNAME=AGENTKIT_ENV_LOADED"
  chmod 644 "${BOX}/home/.config/agentkit/env"
  out="$(ak -- claude)"
  expect_has "a readable env file triggers a chmod 600 warning" "${out}" "chmod 600"
}
