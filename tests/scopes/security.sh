# shellcheck shell=bash
# Planted secrets never leak: every verb, every error path and every file the
# kit writes is searched for the planted values. Plus the static rules.

SEC_VALUES="sec-zai-default-7Q1 sec-zai-work-7Q2 sec-xai-default-7Q3 sec-xai-work-7Q4 sec-azure-default-7Q5 sec-azure-work-7Q6 sec-unrelated-token-7Q7"

sec_env_file() {
  box_env_file ZAI_CODING_API_KEY=sec-zai-default-7Q1 ZAI_CODING_API_KEY_WORK=sec-zai-work-7Q2 \
    XAI_API_KEY=sec-xai-default-7Q3 XAI_API_KEY_WORK=sec-xai-work-7Q4 \
    AZURE_OPENAI_API_KEY=sec-azure-default-7Q5 AZURE_OPENAI_API_KEY_WORK=sec-azure-work-7Q6 \
    AZURE_OPENAI_RESOURCE=res AZURE_OPENAI_MODEL_DAILY=dep GITHUB_TOKEN=sec-unrelated-token-7Q7
}

# leaked <file...> — prints the planted values found in the files.
leaked() {
  local v
  for v in ${SEC_VALUES}; do
    grep -rqF -- "${v}" "$@" 2>/dev/null && printf '%s ' "${v}"
  done
  return 0
}

scope_security() {
  local out k p status root found
  box_new security
  sec_env_file
  root="${BOX}/home/.local/share/agentkit/profiles"
  for k in claude codex cursor opencode pi cline grok; do ak -- profiles add "${k}" @work >/dev/null; done
  printf '{"oauthAccount":{}}\n' > "${BOX}/home/.claude.json"
  mkdir -p "${BOX}/home/.codex" "${BOX}/home/.grok"; printf '{}\n' > "${BOX}/home/.codex/auth.json"; printf '{}\n' > "${BOX}/home/.grok/auth.json"
  : > "${BOX}/kit-output"

  # What the kit itself prints (stderr of launches; all of every other verb).
  # Fakes run in quiet mode for secrets: only the kit can leak here.
  for k in claude claude-glm codex codex-glm codex-azure codex-xai cursor opencode opencode-glm opencode-azure opencode-xai \
      pi pi-glm pi-azure pi-xai grok; do
    for p in "" "@work"; do
      # shellcheck disable=SC2086
      ak_split -- "${k}" ${p} -c
      cat "${BOX}/err" >> "${BOX}/kit-output"
      # the CLI's argv: only Cline may carry a key (documented exception)
      sed -n 's/^ARG=//p' "${BOX}/out" >> "${BOX}/argv-noncline"
      # shellcheck disable=SC2086
      ak_split FAKE_MODE=headless -- run "${k}" ${p} --output-format json -- "hello"
      cat "${BOX}/out" >> "${BOX}/kit-output"
      grep -v '^{"type"' "${BOX}/err" >> "${BOX}/kit-output"
      # shellcheck disable=SC2086
      ak_split -- env "${k}" ${p}
      cat "${BOX}/out" "${BOX}/err" >> "${BOX}/kit-output"
    done
  done
  for args in "doctor" "doctor --json" "profiles" "profiles ls" "profiles path claude @work" "alias" "install" "--help" "" \
      "claude-glm @nokey" "codex-azure @ghost" "run claude-glm @nokey -- x" "run claude-glm @nokey --output-format json -- x" \
      "env claude-glm @nokey" "claude @a/b" "nope" "run nope -- x"; do
    [[ -d "${root}/claude/nokey" ]] || ak -- profiles add claude @nokey >/dev/null
    # shellcheck disable=SC2086
    ak_split -- ${args}
    cat "${BOX}/out" "${BOX}/err" >> "${BOX}/kit-output"
  done
  ak_split AGENTKIT_PERMISSIONS=bogus -- claude-glm
  cat "${BOX}/out" "${BOX}/err" >> "${BOX}/kit-output"
  ak_split AGENTKIT_DEBUG=1 -- claude-glm @nokey
  cat "${BOX}/out" "${BOX}/err" >> "${BOX}/kit-output"
  found="$(leaked "${BOX}/kit-output")"
  expect_eq "no planted value in anything the kit printed (launch, run, env, doctor, profiles, alias, install, errors)" "${found}" ""
  found="$(leaked "${BOX}/argv-noncline")"
  expect_eq "no planted value on any non-Cline command line" "${found}" ""

  # Cline: the key is on its argv by design (documented), never in kit output.
  ak_split FAKE_LOG="${BOX}/cline.log" -- cline-xai @work
  check "cline-xai receives the profile's key on its command line (documented exception)" grep -qx 'ARG=sec-xai-work-7Q4' "${BOX}/cline.log"
  grep '^ak' "${BOX}/err" > "${BOX}/err-kit" || true
  expect_eq "cline-xai: the kit's own messages carry no key (Cline's own auth output aside)" "$(leaked "${BOX}/err-kit")" ""
  check "only Cline kinds may put {key} on a command line (data rule)" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
m = kinds.load()
argv_key = sorted(k for k in m.kind_names() if kinds.references_secret(m.kinds[k].get("args", []) + m.kinds[k].get("pre", [])))
assert argv_key == ["cline-azure", "cline-xai"], argv_key' "${ROOT}"

  # Files the kit writes: config writers, profiles, aliases, rc, install, hooks.
  ak -- alias add w claude-glm @work >/dev/null
  ak -- alias preset classic --on >/dev/null
  box_run -- bash "${ROOT}/install.sh" >/dev/null
  printf '#!/bin/sh\n' > "${BOX}/hook.sh"; mkdir -p "${BOX}/home/.claude/hooks"; cp "${BOX}/hook.sh" "${BOX}/home/.claude/hooks/herdr-agent-state.sh"
  ak -- profiles hooks claude @work >/dev/null
  found="$(cd "${BOX}/home" && find . -type f ! -path './.config/agentkit/env' -print0 | xargs -0 grep -lF -e sec-zai -e sec-xai -e sec-azure -e sec-unrelated 2>/dev/null | tr '\n' ' ')"
  expect_eq "no planted value in any file under HOME except the user's env file" "${found}" ""
  for f in "${root}/codex/work/glm.config.toml" "${BOX}/home/.codex/azure.config.toml" "${root}/pi/work/models.json" \
      "${BOX}/home/.config/agentkit/aliases.json"; do
    expect_eq "mode 600: ${f#"${BOX}/home/"}" "$(file_mode "${f}")" 600
  done
  for d in "${root}" "${root}/claude/work" "${BOX}/home/.local/share/agentkit"; do
    expect_eq "mode 700: ${d#"${BOX}/home/"}" "$(file_mode "${d}")" 700
  done

  # The env file: shell code, so others must not be able to write it.
  chmod 664 "${BOX}/home/.config/agentkit/env"
  out="$(ak -- claude)"; status=$?
  expect_eq "a group-writable env file is refused (exit 70), nothing launched" "${status}:$(grep -c '^CLI=' <<<"${out}")" "70:0"
  expect_has "the refusal says why and how to fix it" "${out}" "chmod 600"
  chmod 646 "${BOX}/home/.config/agentkit/env"
  out="$(ak -- claude)"; status=$?
  expect_eq "a world-writable env file is refused" "${status}" 70
  chmod 640 "${BOX}/home/.config/agentkit/env"
  out="$(ak -- claude)"; status=$?
  expect_eq "a group-readable env file only warns" "${status}:$(grep -c 'chmod 600' <<<"${out}")" "0:1"
  chmod 600 "${BOX}/home/.config/agentkit/env"

  # What a CLI receives.
  out="$(ak FAKE_ENV_NAMES=1 -- claude-glm @work)"
  expect_lacks "a CLI never receives the per-profile key variables" "${out}" "ENVNAME=ZAI_CODING_API_KEY_WORK"
  expect_lacks "a CLI never receives the kit's bookkeeping" "${out}" "ENVNAME=AGENTKIT_ENV_LOADED"

  # Static rules over the code and the shipped files.
  if grep -rnE 'shell=True|os\.system\(|\beval\(|\bexec\(' "${ROOT}/lib"/*.py >/dev/null; then
    fail "lib/*.py uses a shell string, os.system, eval or exec"
  else pass "lib/*.py runs commands as argv lists only (no shell=True, os.system, eval, exec)"; fi
  if grep -rnE '\beval\b' "${ROOT}/bin" "${ROOT}/lib"/*.sh "${ROOT}/install.sh" >/dev/null; then
    fail "a shell script uses eval"
  else pass "no eval in the shell launchers or the installer"; fi
  if grep -rnE '(curl|wget)[^|]*\|[[:space:]]*(ba|z)?sh' "${ROOT}/bin" "${ROOT}/lib" "${ROOT}/skills" "${ROOT}/install.sh" \
      "${ROOT}/install.ps1" "${ROOT}/docs" "${ROOT}/README.md" >/dev/null; then
    fail "a fetch-piped-to-shell line is spelled somewhere in the product"
  else pass "no fetch-piped-to-shell line anywhere in the product or its docs"; fi
  check "every install channel is https and pinned or states why not" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
for c in kinds.load().clis.values():
    i = c["install"]
    assert i["channel"] == "npm" or i["url"].startswith("https://"), i
    assert i.get("version") or i.get("unpinned"), i' "${ROOT}"
  check "docs/SECURITY.md exists and covers the threat model" grep -q '^## Threat model' "${ROOT}/docs/SECURITY.md"
}
