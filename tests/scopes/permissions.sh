# shellcheck shell=bash
# Permission posture: autonomy by default (the CLI's own autonomy flag on
# every launch), with an opt-out that always wins: --ask or
# AGENTKIT_PERMISSIONS=ask.

AUTONOMY_FLAGS="--dangerously-skip-permissions --dangerously-bypass-approvals-and-sandbox --force --yolo --auto --approve --always-approve"

# The autonomy flags present in an argv (one per line).
autonomy_in() {
  local argv="$1" f
  for f in ${AUTONOMY_FLAGS}; do
    printf '%s\n' "${argv}" | tr '|' '\n' | grep -cxF -- "${f}" | sed "s/^/${f} /" | grep -v ' 0$'
  done
  return 0
}

scope_permissions() {
  local out row k flag got status
  box_new permissions
  box_env_file ZAI_CODING_API_KEY=fake-zai XAI_API_KEY=fake-xai AZURE_OPENAI_API_KEY=fake-azure \
    AZURE_OPENAI_RESOURCE=res AZURE_OPENAI_MODEL_DAILY=dep
  # kind | the CLI's own autonomy flag (providers.toml, contract §2.1)
  local -a table=(
    "claude|--dangerously-skip-permissions" "claude-glm|--dangerously-skip-permissions"
    "codex|--dangerously-bypass-approvals-and-sandbox" "codex-glm|--dangerously-bypass-approvals-and-sandbox"
    "codex-azure|--dangerously-bypass-approvals-and-sandbox" "codex-xai|--dangerously-bypass-approvals-and-sandbox"
    "cursor|--force"
    "opencode|--auto" "opencode-glm|--auto" "opencode-azure|--auto" "opencode-xai|--auto"
    "pi|--approve" "pi-glm|--approve" "pi-azure|--approve" "pi-xai|--approve"
    "cline|--yolo" "cline-azure|--yolo" "cline-xai|--yolo"
    "grok|--always-approve"
  )
  for row in "${table[@]}"; do
    k="${row%%|*}"; flag="${row#*|}"
    ak_split -- "${k}"
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k}: exactly ${flag} by default" "${got}" "${flag} 1"
    ak_split -- "${k}" --auto
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} --auto: exactly ${flag} (explicit, same as the default)" "${got}" "${flag} 1"
    ak_split -- "${k}" --ask
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} --ask: no autonomy flag" "${got}" ""
    ak_split AGENTKIT_PERMISSIONS=ask -- "${k}"
    got="$(autonomy_in "$(argv_of "$(cat "${BOX}/out")")")"
    expect_eq "${k} with AGENTKIT_PERMISSIONS=ask: no autonomy flag" "${got}" ""
  done

  # Position: --ask / --auto may sit before or after the profile and the session flag.
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude @2 -c)"
  expect_eq "ak claude @2 -c (the default adds the flag)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  expect_line "the profile applies" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude --ask @2 -c)"
  expect_eq "ak claude --ask @2 -c" "$(argv_of "${out}")" "--continue|--permission-mode|default"
  expect_line "the profile still applies after --ask" "${out}" "CLAUDE_CONFIG_DIR=${BOX}/home/.local/share/agentkit/profiles/claude/2"
  out="$(ak -- claude @2 -c --ask)"
  expect_eq "ak claude @2 -c --ask" "$(argv_of "${out}")" "--continue|--permission-mode|default"
  out="$(ak -- claude --auto @2 -c)"
  expect_eq "ak claude --auto @2 -c (explicit)" "$(argv_of "${out}")" "--continue|--dangerously-skip-permissions"
  out="$(ak -- claude --ask -- --auto)"
  expect_eq "after --, --auto is the CLI's argument" "$(argv_of "${out}")" "--permission-mode|default|--auto"
  out="$(ak -- claude --ask fix --auto)"
  expect_eq "--auto after a CLI argument is the CLI's" "$(argv_of "${out}")" "--permission-mode|default|fix|--auto"
  out="$(ak -- claude --ask --auto)"; status=$?
  expect_eq "--ask with --auto is a usage error" "${status}" 2
  expect_has "the contradiction is explained" "${out}" "--ask and --auto contradict each other"

  # The flag wins over the environment; the environment wins over the default.
  out="$(ak AGENTKIT_PERMISSIONS=ask -- codex --auto)"
  expect_eq "AGENTKIT_PERMISSIONS=ask wins over an explicit --auto (an agent cannot type its way out)" "$(argv_of "${out}")" "--ask-for-approval|on-request|--sandbox|workspace-write"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- codex --ask)"
  expect_eq "--ask overrides AGENTKIT_PERMISSIONS=auto" "$(argv_of "${out}")" "--ask-for-approval|on-request|--sandbox|workspace-write"
  out="$(ak AGENTKIT_PERMISSIONS=ASK -- codex)"
  expect_eq "AGENTKIT_PERMISSIONS is case-insensitive" "$(argv_of "${out}")" "--ask-for-approval|on-request|--sandbox|workspace-write"
  out="$(ak AGENTKIT_PERMISSIONS=yolo -- codex)"; status=$?
  expect_eq "an invalid AGENTKIT_PERMISSIONS is a usage error" "${status}" 2
  expect_has "the invalid value is explained" "${out}" "AGENTKIT_PERMISSIONS must be 'ask' or 'auto'"
  expect_eq "an invalid AGENTKIT_PERMISSIONS launches nothing" "$(grep -c '^CLI=' <<<"${out}")" 0
  box_env_file AGENTKIT_PERMISSIONS=ask
  out="$(ak -- grok)"
  expect_eq "AGENTKIT_PERMISSIONS=ask in the env file opts out" "$(argv_of "${out}")" "--permission-mode|default"
  out="$(ak -- grok --auto)"
  expect_eq "the env-file opt-out also wins over --auto" "$(argv_of "${out}")" "--permission-mode|default"
  # The v0.1 opt-in line in an env file never overrides an inherited opt-out:
  # a nested ak (started by an agent that asked) re-reads the file.
  box_env_file AGENTKIT_PERMISSIONS=auto
  out="$(ak AGENTKIT_PERMISSIONS=ask -- claude)"
  expect_eq "an inherited ask outranks AGENTKIT_PERMISSIONS=auto in the env file (bash launcher)" "$(argv_of "${out}")" "--permission-mode|default"
  out="$(box_run AGENTKIT_PERMISSIONS=ask -- "${AK_PY}" "${ROOT}/lib/ak.py" claude)"
  expect_eq "an inherited ask outranks the env file in the python core (the Windows path)" "$(argv_of "${out}")" "--permission-mode|default"
  out="$(ak -- claude)"
  expect_eq "AGENTKIT_PERMISSIONS=auto in the env file alone is autonomy" "$(argv_of "${out}")" "--dangerously-skip-permissions"
  box_env_file ZAI_CODING_API_KEY=fake-zai

  # The opt-out is inherited by what the agent starts; autonomy is not exported.
  out="$(ak AGENTKIT_PERMISSIONS=ask -- claude)"
  expect_line "an opted-out launch passes AGENTKIT_PERMISSIONS=ask on" "${out}" "AGENTKIT_PERMISSIONS=ask"
  out="$(ak -- claude --ask)"
  expect_line "--ask passes AGENTKIT_PERMISSIONS=ask on (a nested ak asks too)" "${out}" "AGENTKIT_PERMISSIONS=ask"
  out="$(ak AGENTKIT_PERMISSIONS=auto -- claude)"
  expect_line "an autonomous launch does not export AGENTKIT_PERMISSIONS" "${out}" "AGENTKIT_PERMISSIONS="

  # Listing modes never carry an autonomy flag.
  out="$(ak -- cursor -l)"
  expect_eq "cursor -l stays a plain listing" "$(argv_of "${out}")" "ls"
  out="$(ak -- cline -r)"
  expect_eq "cline -r stays a plain history" "$(argv_of "${out}")" "history"

  # The flags exist only as data: no code path spells one.
  if grep -rnE -- '--dangerously|--yolo|--always-approve|"--force"|"--approve"' "${ROOT}/lib" "${ROOT}/bin" >/dev/null; then
    fail "an autonomy flag is spelled in lib/ or bin/ code"
  else
    pass "autonomy flags live only in providers.toml (auto = …)"
  fi
  check "every CLI declares its autonomy flag" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
m = kinds.load()
want = {"claude": ["--dangerously-skip-permissions"], "codex": ["--dangerously-bypass-approvals-and-sandbox"],
        "cursor": ["--force"], "opencode": ["--auto"], "pi": ["--approve"], "cline": ["--yolo"], "grok": ["--always-approve"],
        "antigravity": ["--dangerously-skip-permissions"]}
assert {c: m.clis[c]["auto"] for c in m.clis} == want' "${ROOT}"

  # --- ask is forced, not assumed (an account whose own settings default to
  # an autonomous mode still starts asking): kind | the CLI's explicit ask
  # flag ("" = the CLI has none; omitting its autonomy flag is its ask mode).
  local -a asktable=(
    "claude|--permission-mode|default" "claude-glm|--permission-mode|default"
    "codex|--ask-for-approval|on-request|--sandbox|workspace-write" "codex-glm|-p|glm|--ask-for-approval|on-request|--sandbox|workspace-write"
    "cursor|" "opencode|" "pi|" "cline|" "grok|--permission-mode|default" "antigravity|"
  )
  for row in "${asktable[@]}"; do
    k="${row%%|*}"; flag="${row#*|}"
    out="$(ak -- "${k}" --ask)"
    expect_eq "${k} --ask: exactly the CLI's ask flag '${flag}'" "$(argv_of "${out}")" "${flag}"
    out="$(ak AGENTKIT_PERMISSIONS=ask -- "${k}" --auto)"
    expect_eq "${k} under AGENTKIT_PERMISSIONS=ask (even with --auto): exactly '${flag}'" "$(argv_of "${out}")" "${flag}"
  done
  # Placement: where the autonomy flag would sit, after the session segment.
  local -a placed=(
    "claude -c|--continue|--permission-mode|default"
    "codex -c|resume|--last|--ask-for-approval|on-request|--sandbox|workspace-write"
    "codex -r abc|resume|abc|--ask-for-approval|on-request|--sandbox|workspace-write"
    "grok -c|--continue|--permission-mode|default"
  )
  for row in "${placed[@]}"; do
    # shellcheck disable=SC2086
    out="$(ak -- ${row%%|*} --ask)"
    expect_eq "ak ${row%%|*} --ask: the ask flag after the session" "$(argv_of "${out}")" "${row#*|}"
  done

  # --- a user mode flag cannot undo the opt-out: kind | an argument after --
  # that would set the CLI's permission mode. Refused (exit 2, nothing
  # launched) under the opt-out; passed through untouched under autonomy.
  local -a undo=(
    "claude|--dangerously-skip-permissions" "claude|--permission-mode|bypassPermissions"
    "claude|--permission-mode=auto" "claude|--allow-dangerously-skip-permissions"
    "codex|--dangerously-bypass-approvals-and-sandbox" "codex|-a|never" "codex|--ask-for-approval=never"
    "codex|-c|approval_policy=never" "codex|--sandbox|danger-full-access" "codex|--approve-for-me"
    "codex|--sandbox=danger-full-access" "codex|-sdanger-full-access" "codex|-s|danger-full-access"
    "codex|--config=approval_policy=never" "codex|-capproval_policy=never" "codex|-c|approval_policy =never"
    "codex|--config|sandbox_mode=danger-full-access" "codex|-anever" "codex|x|--yolo"
    "cursor|--force" "cursor|-f" "cursor|--yolo" "cursor|--auto-review" "cursor|-fw" "cursor|-wf"
    "opencode|--auto" "pi|--approve" "pi|-a" "cline|--yolo"
    "grok|--always-approve" "grok|--permission-mode|bypassPermissions"
    "antigravity|--dangerously-skip-permissions" "antigravity|--mode|auto"
    "antigravity|-dangerously-skip-permissions" "antigravity|-mode|auto" "antigravity|-mode=auto"
    "codex|-c=sandbox_mode=danger-full-access" "codex|-s=danger-full-access"
    "codex|-c|profiles.x.sandbox_mode=danger-full-access" "codex|-c|profiles.x.approval_policy=never"
    "claude|--model|--|--dangerously-skip-permissions"
    "codex|-c|sandbox_workspace_write.network_access=true" "codex|-c|sandbox_permissions=[\"disk-full-read-access\"]"
  )
  local -a extra
  for row in "${undo[@]}"; do
    k="${row%%|*}"; IFS='|' read -r -a extra <<<"${row#*|}"
    ak_split -- "${k}" --ask -- "${extra[@]}"; status=$?
    expect_eq "${k} --ask -- ${extra[*]}: refused (exit 2)" "${status}" 2
    expect_eq "${k} --ask -- ${extra[*]}: launches nothing" "$(grep -c '^CLI=' "${BOX}/out")" 0
    expect_has "${k} --ask -- ${extra[*]}: the refusal names the argument" "$(cat "${BOX}/err")" "would change"
    ak_split AGENTKIT_PERMISSIONS=ask -- "${k}" -- "${extra[@]}"; status=$?
    expect_eq "${k} -- ${extra[*]} under AGENTKIT_PERMISSIONS=ask: refused (exit 2)" "${status}" 2
    ak_split AGENTKIT_PERMISSIONS=auto -- "${k}" -- "${extra[@]}"; status=$?
    expect_eq "${k} -- ${extra[*]} under autonomy: the CLI's own argument (exit 0)" "${status}" 0
  done
  out="$(ak -- claude --ask fix --dangerously-skip-permissions)"; status=$?
  expect_eq "a mode flag after a CLI argument is refused too" "${status}" 2
  # What stays allowed under the opt-out: stricter modes (providers.toml
  # ask_values), unrelated options and config keys, other value-taking short
  # options, and plain words — a prompt is never matched.
  local -a allowed=(
    "claude|--permission-mode|plan" "claude|--permission-mode=plan" "claude|--permission-mode|manual"
    "grok|--permission-mode|plan" "antigravity|--mode|plan"
    "codex|-s|read-only" "codex|--sandbox=workspace-write" "codex|-c|model=o3" "codex|-cmodel_reasoning_effort=high"
    "codex|-pazure" "codex|danger-full-access" "codex|explain|--approve-for-me-docs" "codex|--|--yolo"
    "cursor|-w" "pi|-na" "pi|explain" "claude|-p|x"
    "claude|--permission-mode|dontAsk" "codex|-s=read-only" "antigravity|-mode|plan" "claude|x|--|--dangerously-skip-permissions"
  )
  for row in "${allowed[@]}"; do
    k="${row%%|*}"; IFS='|' read -r -a extra <<<"${row#*|}"
    ak_split -- "${k}" --ask -- "${extra[@]}"; status=$?
    expect_eq "${k} --ask -- ${extra[*]}: allowed (exit 0)" "${status}" 0
  done
  # A stricter sandbox the user passes replaces ak's pinned one (codex
  # refuses the option twice).
  out="$(ak -- codex --ask -- -s read-only)"
  expect_eq "codex --ask -- -s read-only: the user's stricter sandbox replaces ak's" "$(argv_of "${out}")" "--ask-for-approval|on-request|-s|read-only"
  out="$(ak -- codex --ask -- -c model=o3)"
  expect_eq "an unrelated config override passes untouched after the ask flag" "$(argv_of "${out}")" "--ask-for-approval|on-request|--sandbox|workspace-write|-c|model=o3"

  # Headless (ak run) under the opt-out: the run scope's argv table (claude and
  # grok carry their ask flag; codex exec pins only its sandbox, providers.toml run.ask).

  # The ask flags are data too: no code path spells one.
  if grep -rnE -- '--permission-mode|on-request|--ask-for-approval' "${ROOT}/lib" "${ROOT}/bin" >/dev/null; then
    fail "an ask flag is spelled in lib/ or bin/ code"
  else
    pass "ask flags live only in providers.toml (ask = …)"
  fi
  check "every CLI declares ask and ask_conflicts, and its autonomy flag is a conflict" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
m = kinds.load()
for c, cli in m.clis.items():
    assert isinstance(cli.get("ask"), list), c
    assert set(cli["auto"]) <= set(cli.get("ask_conflicts", [])), c' "${ROOT}"
}
