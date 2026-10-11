# shellcheck shell=bash
# Planted secrets never leak: every verb, every error path and every file the
# kit writes is searched for the planted values. Plus the static rules.

SEC_VALUES="sec-usage-claude-7Q8 sec-usage-refresh-7Q9 sec-zai-default-7Q1 sec-zai-work-7Q2 sec-xai-default-7Q3 sec-xai-work-7Q4 sec-azure-default-7Q5 sec-azure-work-7Q6 sec-unrelated-token-7Q7"

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
  # Text only (-I) and no bytecode: a .pyc marshals unrelated constants next to
  # each other, so "curl" ... "|" ... "sh" can line up in binary data.
  if grep -rnIE --exclude-dir=__pycache__ '(curl|wget)[^|]*\|[[:space:]]*(ba|z)?sh' "${ROOT}/bin" "${ROOT}/lib" "${ROOT}/skills" "${ROOT}/install.sh" \
      "${ROOT}/install.ps1" "${ROOT}/docs" "${ROOT}/README.md" >/dev/null; then
    fail "a fetch-piped-to-shell line is spelled somewhere in the product"
  else pass "no fetch-piped-to-shell line anywhere in the product or its docs"; fi
  check "every install channel is https, pinned and verified (no unverified exception ships)" "${AK_PY}" -c '
import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import kinds
for c in kinds.load().clis.values():
    i = c["install"]
    assert i["channel"] == "npm" or i["url"].startswith("https://"), i
    assert i.get("version") and not kinds.install_problems(i) and not i.get("unverified"), i' "${ROOT}"
  check "docs/SECURITY.md exists and covers the threat model" grep -q '^## Threat model' "${ROOT}/docs/SECURITY.md"

  # --- regressions for the pre-release review ----------------------------------
  mkdir -p "${SANDBOX}/review"
  py_checks review_checks.py "${ROOT}" "${SANDBOX}/review"
  box_new security-review
  sec_env_file
  ak -- profiles add claude @work >/dev/null
  out="$(ak FAKE_ENV_NAMES=1 AGENTKIT_PERMISSIONS=auto -- profiles run claude @work -- claude)"
  expect_lacks "profiles run strips per-profile keys" "${out}" "ENVNAME=ZAI_CODING_API_KEY_WORK"
  expect_lacks "profiles run drops AGENTKIT_PERMISSIONS" "${out}" "ENVNAME=AGENTKIT_PERMISSIONS"
  ak -- profiles add claude @a-b >/dev/null
  ak_split -- profiles add claude @a_b; status=$?
  expect_eq "a profile whose key suffix collides is refused" "${status}:$(test -e "${root}/claude/a_b" && echo made || echo none)" "2:none"
  mkdir -p "${BOX}/dotfiles"; printf '# dot\n' > "${BOX}/dotfiles/zshrc"; ln -s "${BOX}/dotfiles/zshrc" "${BOX}/home/.zshrc"
  ak -- alias add w claude >/dev/null
  if [[ -L "${BOX}/home/.zshrc" ]] && grep -q '>>> agentkit' "${BOX}/dotfiles/zshrc"; then pass "a symlinked rc stays a symlink; the block lands in its target"; else fail "the rc symlink was replaced"; fi
  mkdir -p "${BOX}/home/.config"; printf '{}\n' > "${BOX}/dotfiles/opencode.json"; mkdir -p "${BOX}/home/.config/opencode"
  ln -s "${BOX}/dotfiles/opencode.json" "${BOX}/home/.config/opencode/opencode.json"
  ak -- opencode-xai >/dev/null
  if [[ -L "${BOX}/home/.config/opencode/opencode.json" ]] && grep -q '"xai"' "${BOX}/dotfiles/opencode.json"; then pass "a symlinked provider config is updated through the link"; else fail "the opencode.json symlink was replaced"; fi
  printf '{"classic": false, "custom": [{"name": "x; touch pwned #", "kind": "claude"}, {"name": "ok_one", "kind": "claude; id"}]}\n' > "${BOX}/home/.config/agentkit/aliases.json"
  ak -- alias add good claude >/dev/null
  if grep -q 'pwned\|; id' "${BOX}/home/.local/share/agentkit/aliases.sh"; then fail "a tampered aliases.json reached aliases.sh"; else pass "aliases.json is re-validated before rendering shell functions"; fi
  ak_split -- run claude -- --dangerously-skip-permissions; status=$?
  expect_eq "ak run refuses a prompt that starts with - (it could be read as a flag)" "${status}" 2
  ak_split -- run claude --timeout inf -- hello; status=$?
  expect_eq "ak run --timeout inf is a usage error, not a crash" "${status}" 2
  printf '{"oauthAccount":{}}\n' > "${BOX}/home/.claude.json"
  ak_split FAKE_CHILD_PID="${BOX}/left.pid" -- run claude -- hello
  sleep 0.3
  local left
  left="$(cat "${BOX}/left.pid" 2>/dev/null)"
  if [[ -n "${left}" ]] && ! kill -0 "${left}" 2>/dev/null; then pass "nothing a finished run started outlives it"; else fail "a grandchild outlived a finished run (pid ${left})"; fi
  box_new security-prefix
  mkdir -p "${BOX}/home/.local/bin" "${BOX}/home/.local/lib/python3/site-packages"
  touch "${BOX}/home/.local/bin/mytool"
  out="$(box_run AGENTKIT_HOME="${BOX}/home/.local" -- bash "${ROOT}/install.sh" --no-rc)"; status=$?
  if [[ "${status}" -ne 0 && -e "${BOX}/home/.local/bin/mytool" && -d "${BOX}/home/.local/lib/python3/site-packages" ]]; then
    pass "install.sh refuses a non-kit AGENTKIT_HOME and deletes nothing"
  else fail "install.sh used a foreign directory (exit ${status})"; fi
  out="$(box_run AGENTKIT_HOME="${BOX}/home/.local" -- bash "${ROOT}/install.sh" --uninstall)"; status=$?
  if [[ "${status}" -ne 0 && -e "${BOX}/home/.local/bin/mytool" ]]; then pass "--uninstall refuses a directory without the install marker"; else fail "--uninstall removed from a foreign directory"; fi
  box_new security-norc
  box_run -- bash "${ROOT}/install.sh" --no-rc >/dev/null
  box_run -- "${BOX}/home/.local/share/agentkit/bin/ak" alias preset classic --on >/dev/null
  if [[ -e "${BOX}/home/.zshrc" || -e "${BOX}/home/.bashrc" || -e "${BOX}/home/.profile" ]]; then fail "--no-rc was forgotten by ak alias"; else pass "an install made with --no-rc keeps ak alias away from rc files"; fi

  # Writes confined to the profile even through planted symlinks (verification pass).
  box_new security-confine
  sec_env_file
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${BOX}/home/.claude/hooks"; printf '#!/bin/sh\n' > "${BOX}/home/.claude/hooks/herdr-agent-state.sh"
  printf '{"hooks":{"SessionStart":[{"hooks":[{"command":"bash %s/.claude/hooks/herdr-agent-state.sh"}]}]}}\n' "${BOX}/home" > "${BOX}/home/.claude/settings.json"
  printf '# victim rc\n' > "${BOX}/home/.zshrc"
  ak -- profiles add claude @evil >/dev/null
  mkdir -p "${root}/claude/evil/hooks"
  ln -s "${BOX}/home/.zshrc" "${root}/claude/evil/hooks/herdr-agent-state.sh"
  ak_split -- profiles hooks claude @evil; status=$?
  expect_eq "hooks: a planted symlinked hook file is refused and its target untouched" "${status}:$(cat "${BOX}/home/.zshrc")" "3:# victim rc"
  rm -f "${root}/claude/evil/hooks/herdr-agent-state.sh"
  cp "${BOX}/home/.claude/settings.json" "${BOX}/settings.before"
  ln -s "${BOX}/home/.claude/settings.json" "${root}/claude/evil/settings.json"
  ak_split -- profiles hooks claude @evil; status=$?
  if [[ "${status}" -eq 3 ]] && cmp -s "${BOX}/home/.claude/settings.json" "${BOX}/settings.before"; then
    pass "hooks: a planted symlinked registration is refused; the real home's settings untouched"
  else fail "hooks wrote through a planted registration symlink (exit ${status})"; fi
  ak -- profiles add codex @evil >/dev/null
  printf '# Generated by coding-agents-kit (ak); do not hand-edit.\nmodel = "x"\n' > "${BOX}/outside.toml"
  ln -s "${BOX}/outside.toml" "${root}/codex/evil/glm.config.toml"
  ak_split -- codex-glm @evil; status=$?
  expect_eq "writers: a profile's planted config symlink is refused (nothing written outside)" "${status}:$(grep -c '^model = "x"$' "${BOX}/outside.toml")" "3:1"

  security_usage
  security_setup
}

# `ak usage` reads credential content and talks to vendor endpoints: the first
# part of the kit that does either. Every promise is a failing-if-broken check.
security_usage() {
  local out status before after dir tok="sec-usage-claude-7Q8" ref="sec-usage-refresh-7Q9" mode
  box_new security-usage claude
  sec_env_file
  dir="${BOX}/home/.claude"
  mkdir -p "${dir}"
  printf '{"claudeAiOauth":{"accessToken":"%s","refreshToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' \
    "${tok}" "${ref}" > "${dir}/.credentials.json"
  chmod 600 "${dir}/.credentials.json"
  printf '%s' '{"/claude":{"json":{"five_hour":{"utilization":10,"resets_at":"2099-01-01T00:00:00Z"}}},"/zai":{"json":{"data":{"limits":[{"type":"TOKENS_LIMIT","percentage":5}]}}}}' > "${BOX}/routes.json"
  usage_server_start "${BOX}/routes.json"
  local base="http://127.0.0.1:${USAGE_PORT}"
  : > "${BOX}/usage-output"
  before="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"

  # Every mode of the server and the command, debug on, output collected.
  for mode in ok 500 401 429 redirect garbage truncated; do
    case "${mode}" in
      ok) printf '%s' '{"/claude":{"json":{"five_hour":{"utilization":10,"resets_at":"2099-01-01T00:00:00Z"}}},"/zai":{"json":{"data":{"limits":[{"type":"TOKENS_LIMIT","percentage":5}]}}}}' > "${BOX}/routes.json" ;;
      500) printf '%s' '{"/claude":{"status":500,"body":"boom"},"/zai":{"status":500,"body":"boom"}}' > "${BOX}/routes.json" ;;
      401) printf '%s' '{"/claude":{"status":401,"body":"{}"},"/zai":{"status":401,"body":"{}"}}' > "${BOX}/routes.json" ;;
      429) printf '%s' '{"/claude":{"status":429,"body":"{}"},"/zai":{"status":429,"body":"{}"}}' > "${BOX}/routes.json" ;;
      redirect) printf '%s' '{"/claude":{"redirect":"/elsewhere"},"/zai":{"redirect":"/elsewhere"},"/elsewhere":{"json":{}}}' > "${BOX}/routes.json" ;;
      garbage) printf '%s' '{"/claude":{"body":"<html>nope</html>"},"/zai":{"body":"<html>nope</html>"}}' > "${BOX}/routes.json" ;;
      truncated) printf '%s' '{"/claude":{"body":"{\"five_hour\": "},"/zai":{"body":"{\"data\": "}}' > "${BOX}/routes.json" ;;
    esac
    ak_split AGENTKIT_DEBUG=1 AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH="${base}/claude" AGENTKIT_USAGE_URL_ZAI_QUOTA="${base}/zai" -- usage
    cat "${BOX}/out" "${BOX}/err" >> "${BOX}/usage-output"
    ak_split AGENTKIT_DEBUG=1 AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH="${base}/claude" AGENTKIT_USAGE_URL_ZAI_QUOTA="${base}/zai" -- usage --json
    cat "${BOX}/out" "${BOX}/err" >> "${BOX}/usage-output"
  done
  expect_eq "security usage: no key, access token or refresh token in any output, in any failure mode" "$(leaked "${BOX}/usage-output")" ""
  expect_lacks "security usage: the server log holds only hashed credentials" "$(cat "${BOX}/server.log")" "${tok}"
  expect_eq "security usage: a redirect target was never requested" "$(grep -c '"/elsewhere"' "${BOX}/server.log")" 0
  expect_eq "security usage: only the two usage paths were ever requested (no refresh or token endpoint)" \
    "$(grep -o '"path": "[^"]*"' "${BOX}/server.log" | sort -u | tr '\n' ' ')" '"path": "/claude" "path": "/zai" '
  after="$(find "${BOX}/home" -type f | sort | xargs -r cksum)"
  expect_eq "security usage: the credentials and the env file are byte-identical after every run" "${before}" "${after}"
  expect_eq "security usage: the credential file mode is untouched" "$(file_mode "${dir}/.credentials.json")" "600"

  # Network rules: nothing leaves loopback, whatever the environment says.
  : > "${BOX}/server.log"
  for out in "http://example.com/x" "https://127.0.0.1.evil.example/x" "http://127.0.0.1@evil.example/x" "file:///etc/passwd" "ftp://127.0.0.1/x"; do
    ak_split AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH="${out}" -- usage claude; status=$?
    expect_eq "security usage: an override to ${out} is refused (exit 2)" "${status}" 2
    expect_has "security usage: ... with a loopback message" "$(cat "${BOX}/err")" "loopback"
  done
  expect_eq "security usage: ... and no request reached the fake endpoint" "$(wc -l < "${BOX}/server.log" | tr -d ' ')" 0

  # Static rules over the module.
  check "security usage: the only subprocess is the optional Keychain read, never through a shell" \
    bash -c '[ "$(grep -c "subprocess\.run" "$1")" -le 1 ] && ! grep -Eq "shell *= *True|os\.system|os\.popen" "$1"' _ "${ROOT}/lib/usage.py"
  check "security usage: the Keychain subprocess runs without any key or token variable" \
    bash -c 'grep -q "secret_like" "$1"' _ "${ROOT}/lib/usage.py"
  check "security usage: no autonomy flag is spelled in lib/usage.py" \
    bash -c '! grep -Eq -- "--dangerously|--yolo|--always-approve|bypass-approvals" "$1"' _ "${ROOT}/lib/usage.py"
  check "security usage: nothing in lib/usage.py fetches into a shell or writes a file" \
    bash -c '! grep -Eq "\| *(ba|z)?sh|open\([^)]*[\"\x27][wa]b?[\"\x27]|os\.(rename|remove|unlink|replace)|shutil|chmod" "$1"' _ "${ROOT}/lib/usage.py"
  check "security usage: no refresh endpoint or grant type appears in lib/usage.py or providers.toml" \
    bash -c '! grep -Eqi "refresh_token *[:=]|grant_type|/oauth/token|/token\b" "$1" "$2"' _ "${ROOT}/lib/usage.py" "${ROOT}/providers.toml"
  usage_server_stop
}

# `ak setup` (the helper behind the agentkit-setup skill) observes and renders;
# it must never print a key, write anything but an explicit --out, apply a
# repair, or render a recipe that breaks the container rules. The skill's
# promises (consent gates, pinned sources) are checked as text.
security_setup() {
  local out digest="8c163a81fa31151cd577797f07cfbe3e61dad49ff691de0b6d5de0975f1cc8ca" before after f gate status
  box_new security-setup
  sec_env_file
  : > "${BOX}/setup-output"
  before="$(find "${BOX}" -type f ! -name setup-output ! -name out ! -name err | sort | xargs -r cksum)"
  for f in "setup probe" "setup probe --json" "setup verify --keys ZAI_CODING_API_KEY,XAI_API_KEY --cli claude --expect-posture ask" \
      "setup verify --json --keys AZURE_OPENAI_API_KEY" "setup docker --ref v0.3.0 --sha256 ${digest} --cli claude,codex" \
      "setup docker --ref v0.3.0 --sha256 ${digest} --format compose" "setup docker --ref v0.3.0 --sha256 ${digest} --format entrypoint" \
      "setup docker --ref v0.3.0 --sha256 ${digest} --format devcontainer" "setup docker --ref main --sha256 ${digest}" "setup docker --ref v0.3.0 --sha256 ${digest} --base alpine"; do
    # shellcheck disable=SC2086
    ak_split GITHUB_TOKEN=sec-unrelated-token-7Q7 -- ${f}
    cat "${BOX}/out" "${BOX}/err" >> "${BOX}/setup-output"
  done
  expect_eq "security setup: no key or token value in any probe, verify or recipe output" "$(leaked "${BOX}/setup-output")" ""
  after="$(find "${BOX}" -type f ! -name setup-output ! -name out ! -name err | sort | xargs -r cksum)"
  expect_eq "security setup: probe, verify and docker write nothing and apply no repair" "${before}" "${after}"
  ak_split -- setup docker --ref v0.3.0 --sha256 "${digest}" --out "${BOX}/work/Dockerfile"
  ak_split -- setup docker --ref v0.3.0 --sha256 "${digest}" --out "${BOX}/work/Dockerfile"; status=$?
  expect_eq "security setup: --out writes a new file once and never overwrites" "${status}:$(grep -c 'FROM ' "${BOX}/work/Dockerfile")" "2:1"
  expect_eq "security setup: the recipe on disk carries no secret value" "$(leaked "${BOX}/work/Dockerfile")" ""

  # The recipe rules hold for every format (the renderer also refuses to print a recipe that breaks them).
  for f in dockerfile compose entrypoint devcontainer; do
    check "security setup: the ${f} recipe passes the container safety rules" \
      "${AK_PY}" -c 'import sys; sys.path.insert(0, sys.argv[1]); import kinds, setup
model = kinds.load()
opts = setup.parse_docker_args(model, ["--ref", "v0.3.0", "--sha256", sys.argv[2], "--format", sys.argv[3], "--cli", "claude,codex"])
sys.exit(1 if setup.recipe_problems(setup.render_docker(model, opts), sys.argv[3]) else 0)' "${ROOT}/lib" "${digest}" "${f}"
  done
  out="$(ak -- setup docker --ref latest --sha256 "${digest}")"; status=$?
  expect_eq "security setup: latest is refused as a ref (exit 2)" "${status}" 2
  out="$(ak -- setup docker --ref v0.3.0)"; status=$?
  expect_eq "security setup: a missing digest is refused, never invented (exit 2)" "${status}" 2

  # Static rules over the helper and the skill.
  check "security setup: lib/setup.py opens no file for writing except through the no-overwrite --out (one O_EXCL create)" \
    bash -c '! grep -Eq "(^|[^a-z_.])open\([^)]*[\"\x27](w|a|r\+)b?[\"\x27]" "$1" && [ "$(grep -c "os\.open(" "$1")" -eq 1 ] && grep -q "O_EXCL" "$1"' _ "${ROOT}/lib/setup.py"
  check "security setup: its only subprocess is the version probe; no shell, no package manager call, no rc edit" \
    bash -c '[ "$(grep -c "subprocess\.run(" "$1")" -eq 1 ] && ! grep -Eq "shell *= *True|os\.system|os\.popen|os\.exec|\[[\"\x27](apt-get|brew|winget|apk|npm|pip)[\"\x27]" "$1"' _ "${ROOT}/lib/setup.py"
  check "security setup: lib/setup.py spells no autonomy flag" \
    bash -c '! grep -Eq -- "--dangerously|--yolo|--always-approve|bypass-approvals" "$1"' _ "${ROOT}/lib/setup.py"
  check "security setup: its child processes run without key or token variables" \
    bash -c 'grep -q "secret_like" "$1"' _ "${ROOT}/lib/setup.py"
  check "security setup: no skill, reference or helper text fetches into a shell or names a branch or latest as a source" \
    bash -c '! grep -rEq "(curl|wget)[^|\n]*\|[[:space:]]*(ba|z)?sh([[:space:]]|$)|--branch (main|master|latest)|releases/latest" "$1" "$2"' _ "${ROOT}/skills/agentkit-setup" "${ROOT}/lib/setup.py"
  for gate in "system package" "shell rc" "posture" "profile" "CLI install" "repository write" "uninstall"; do
    check "security setup: the skill names the consent gate [GATE: ${gate}]" grep -q "\[GATE: ${gate}\]" "${ROOT}/skills/agentkit-setup/SKILL.md"
  done
  check "security setup: the skill forbids typing an autonomy flag or removing the opt-out" \
    grep -q "type an autonomy flag or remove the user's opt-out" "${ROOT}/skills/agentkit-setup/SKILL.md"
}

