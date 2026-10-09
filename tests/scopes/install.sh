# shellcheck shell=bash
# install.sh (sandbox HOME, idempotent, upgrade, uninstall), `ak install`
# channels through fake curl/npm (no network), and the Windows layer's files.

# A fake curl that "downloads" an installer recording its own arguments.
fake_curl() {
  cat > "${BOX}/bin/curl" <<'EOF'
#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift ;; https://*) url="$1" ;; esac
  shift
done
echo "CURL ${url}" >> "${FAKE_NET_LOG}"
[ -n "${FAKE_CURL_FAIL:-}" ] && exit 22
cat > "${out}" <<SCRIPT
#!/bin/sh
echo "INSTALLER ${url} args: \$*" >> "${FAKE_NET_LOG}"
mkdir -p "\${HOME}/.local/bin"
SCRIPT
exit 0
EOF
  cat > "${BOX}/bin/npm" <<'EOF'
#!/bin/sh
echo "NPM $*" >> "${FAKE_NET_LOG}"
exit "${FAKE_NPM_EXIT:-0}"
EOF
  chmod +x "${BOX}/bin/curl" "${BOX}/bin/npm"
}

installed_ak() {
  box_run "$@"
}

scope_install() {
  local dest out status before
  box_new install
  dest="${BOX}/home/.local/share/agentkit"

  # --- fresh install, --no-rc --------------------------------------------------
  out="$(box_run -- bash "${ROOT}/install.sh" --no-rc)"; status=$?
  expect_eq "install.sh --no-rc exits 0" "${status}" 0
  for f in bin/ak bin/agentkit lib/ak.py lib/kinds.py lib/common.sh lib/env.template providers.toml docs/kinds.md LICENSE; do
    check "installed ${f}" test -e "${dest}/${f}"
  done
  check "installed bin/ak is executable" test -x "${dest}/bin/ak"
  expect_eq "the install root is mode 700" "$(file_mode "${dest}")" 700
  out="$(box_run -- "${dest}/bin/ak" --version)"
  expect_eq "the installed ak runs" "${out}" "agentkit 0.1.0 (interface 1)"
  ( cd "${BOX}/work" && env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" "${dest}/bin/ak" doctor --json \
      </dev/null >"${BOX}/doctor.json" 2>/dev/null )
  expect_eq "the installed ak doctor --json reports interface 1 (smoke)" "$(json_get "${BOX}/doctor.json" 'd["interface"]')" 1
  expect_eq "the env file is created mode 600" "$(file_mode "${BOX}/home/.config/agentkit/env")" 600
  expect_eq "the env file's directory is mode 700" "$(file_mode "${BOX}/home/.config/agentkit")" 700
  check "the env file starts from the template (no values)" grep -q '^# ZAI_CODING_API_KEY=$' "${BOX}/home/.config/agentkit/env"
  if [[ -e "${BOX}/home/.zshrc" || -e "${BOX}/home/.bashrc" || -e "${BOX}/home/.profile" ]]; then fail "--no-rc touched a shell rc"; else pass "--no-rc touches no shell rc"; fi
  if find "${dest}" -name '__pycache__' -o -name 'tests' -o -name '.git' -o -name '.dwp' | grep -q .; then
    fail "the install contains tests, caches or repository state"
  else pass "the install holds only the product (no tests/, .git, .dwp, __pycache__)"; fi
  check "the installed bin/ak is byte-identical to the repository's" cmp -s "${ROOT}/bin/ak" "${dest}/bin/ak"

  # --- idempotent, never overwrites the env file, keeps profiles, drops stale files
  printf 'XAI_API_KEY=planted-install-0x1\n' >> "${BOX}/home/.config/agentkit/env"
  mkdir -p "${dest}/profiles/claude/work"
  touch "${dest}/lib/stale_module.py"
  before="$(cat "${BOX}/home/.config/agentkit/env")"
  out="$(box_run -- bash "${ROOT}/install.sh" --no-rc)"; status=$?
  expect_eq "a second install.sh succeeds" "${status}" 0
  expect_eq "install.sh never overwrites the env file" "$(cat "${BOX}/home/.config/agentkit/env")" "${before}"
  check "install.sh keeps profiles" test -d "${dest}/profiles/claude/work"
  check "an upgrade removes stale files of the old version" test ! -e "${dest}/lib/stale_module.py"
  expect_lacks "install.sh prints no key value" "${out}" "planted-install"
  out="$(cd / && env -i HOME="${BOX}/home" PATH="${BOX}/bin:${BASE_PATH}" bash "${ROOT}/install.sh" --no-rc 2>&1)"; status=$?
  expect_eq "install.sh works from another directory" "${status}" 0

  # --- the rc block ------------------------------------------------------------------
  printf '# my zshrc\nexport EDITOR=vim\n' > "${BOX}/home/.zshrc"
  box_run SHELL=/bin/zsh -- bash "${ROOT}/install.sh" >/dev/null
  box_run SHELL=/bin/zsh -- bash "${ROOT}/install.sh" >/dev/null
  expect_eq "install.sh adds exactly one guarded block (idempotent)" "$(grep -c '^# >>> agentkit >>>$' "${BOX}/home/.zshrc")" 1
  check "the user's own rc lines are kept" grep -q '^export EDITOR=vim$' "${BOX}/home/.zshrc"
  check "the block is closed" grep -q '^# <<< agentkit <<<$' "${BOX}/home/.zshrc"
  out="$(box_run -- bash -c ". '${BOX}/home/.zshrc'; command -v ak")"
  expect_eq "sourcing the rc puts the installed ak on PATH" "${out}" "${dest}/bin/ak"
  out="$(box_run -- bash -c ". '${BOX}/home/.zshrc'; . '${BOX}/home/.zshrc'; printf '%s' \"\$PATH\" | tr ':' '\n' | grep -cxF '${dest}/bin'")"
  expect_eq "sourcing the rc twice does not duplicate PATH" "${out}" 1
  check "the block is valid sh" sh -n "${BOX}/home/.zshrc"
  printf '# my bashrc\n' > "${BOX}/home/.bashrc"
  box_run SHELL=/bin/bash -- bash "${ROOT}/install.sh" >/dev/null
  expect_eq "an existing ~/.bashrc gets the block too" "$(grep -c '^# >>> agentkit >>>$' "${BOX}/home/.bashrc")" 1

  # --- uninstall ----------------------------------------------------------------------
  out="$(box_run -- bash "${ROOT}/install.sh" --uninstall)"; status=$?
  expect_eq "install.sh --uninstall exits 0" "${status}" 0
  check "uninstall removes the program" test ! -e "${dest}/bin/ak" -a ! -e "${dest}/lib"
  check "uninstall keeps profiles" test -d "${dest}/profiles/claude/work"
  check "uninstall keeps the env file" test -f "${BOX}/home/.config/agentkit/env"
  expect_eq "uninstall removes the rc block" "$(grep -c 'agentkit' "${BOX}/home/.zshrc")" 0
  expect_eq "uninstall leaves the rest of the rc as it was" "$(cat "${BOX}/home/.zshrc")" "$(printf '# my zshrc\nexport EDITOR=vim')"
  out="$(box_run -- bash "${ROOT}/install.sh" --bogus)"; status=$?
  expect_eq "install.sh with an unknown option exits 2" "${status}" 2
  out="$(box_run -- bash "${ROOT}/install.sh" --help)"; status=$?
  expect_has "install.sh --help explains --no-rc" "${status}:${out}" "0:"
  box_new install-prefix
  box_run AGENTKIT_HOME="${BOX}/elsewhere" -- bash "${ROOT}/install.sh" --no-rc >/dev/null
  check "AGENTKIT_HOME moves the install" test -x "${BOX}/elsewhere/bin/ak"

  # --- ak install: vendor channels, pinned, no network (fake curl/npm) -------------------
  box_new install-clis claude
  fake_curl
  : > "${BOX}/net.log"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install)"; status=$?
  expect_eq "ak install without names only reports" "${status}:$(wc -c < "${BOX}/net.log" | tr -d ' ')" "0:0"
  expect_has "ak install lists what is missing and how" "${out}" "npm install -g @openai/codex@0.158.0"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install claude)"
  expect_has "an installed CLI is skipped" "${out}" "claude: already installed — skip"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install codex-azure pi)"; status=$?
  expect_eq "ak install runs the npm channels" "${status}" 0
  check "codex is installed pinned (npm @openai/codex@0.158.0)" grep -qx 'NPM install -g @openai/codex@0.158.0' "${BOX}/net.log"
  check "pi is installed pinned with --ignore-scripts" grep -qx 'NPM install -g --ignore-scripts @earendil-works/pi-coding-agent@0.85.1' "${BOX}/net.log"
  : > "${BOX}/net.log"
  rm -f "${BOX}/bin/claude"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install claude)"; status=$?
  expect_eq "ak install claude succeeds" "${status}" 0
  check "the vendor script is downloaded over https" grep -qx 'CURL https://claude.ai/install.sh' "${BOX}/net.log"
  check "the downloaded script runs with the pinned version" grep -qx 'INSTALLER https://claude.ai/install.sh args: 2.1.295' "${BOX}/net.log"
  : > "${BOX}/net.log"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install grok)"
  check "an unpinnable vendor script runs without a version" grep -qx 'INSTALLER https://x.ai/cli/install.sh args: ' "${BOX}/net.log"
  expect_has "the plan says why it is unpinned" "$(ak FAKE_NET_LOG="${BOX}/net.log" -- install)" "unpinned"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" FAKE_CURL_FAIL=1 -- install cursor codex)"; status=$?
  expect_eq "a failed download is exit 1" "${status}" 1
  expect_has "one failure does not stop the others" "$(cat "${BOX}/net.log")" "NPM install -g @openai/codex"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" FAKE_NPM_EXIT=1 -- install cline)"; status=$?
  expect_has "a failed npm install is reported" "${status}:${out}" "1:"
  rm -f "${BOX}/bin/npm"
  out="$(ak FAKE_NET_LOG="${BOX}/net.log" -- install opencode)"; status=$?
  expect_has "without npm, ak install says to install Node" "${status}:${out}" "1:"
  expect_has "the Node hint is named" "${out}" "install Node first"
  out="$(ak -- install nope)"; status=$?
  expect_eq "ak install of an unknown CLI is a usage error" "${status}" 2
  if grep -rnE '(curl|wget)[^|]*\|[[:space:]]*(ba|z)?sh' "${ROOT}/lib" "${ROOT}/install.sh" "${ROOT}/install.ps1" >/dev/null; then
    fail "a fetch-piped-to-shell line exists in the kit"
  else pass "no fetch-piped-to-shell line anywhere in the installers"; fi

  # --- the Windows layer ----------------------------------------------------------------
  check "win/ak.cmd and win/agentkit.cmd exist" test -f "${ROOT}/win/ak.cmd" -a -f "${ROOT}/win/agentkit.cmd"
  check "win/ak.cmd runs lib\\ak.py" grep -q 'lib\\ak.py' "${ROOT}/win/ak.cmd"
  check "the .cmd shims use CRLF line endings" grep -q $'\r$' "${ROOT}/win/ak.cmd"
  check "install.ps1 installs both shims and never pipes a download into a shell" \
    bash -c "grep -q \"'ak.cmd', 'agentkit.cmd'\" '${ROOT}/install.ps1' && ! grep -qiE 'iex|Invoke-Expression' '${ROOT}/install.ps1'"
  if command -v pwsh >/dev/null 2>&1; then
    check "pwsh parses install.ps1" pwsh -NoProfile -Command "\$e=\$null; [void][System.Management.Automation.Language.Parser]::ParseFile('${ROOT}/install.ps1',[ref]\$null,[ref]\$e); if (\$e) { exit 1 }"
  else
    skip "PowerShell parse of install.ps1 (no pwsh here; the CI windows job parses and runs it)"
  fi
  out="$(box_run -- env -u AGENTKIT_ENV_LOADED "${AK_PY}" "${ROOT}/lib/ak.py" --version)"
  expect_eq "the python core runs without the bash launcher (the Windows path)" "${out}" "agentkit 0.1.0 (interface 1)"
  box_new install-pyenv
  box_env_file '# comment' 'export ZAI_CODING_API_KEY="planted-quoted-0x1"' "XAI_API_KEY='planted-single'" 'IGNORED LINE'
  out="$(box_run FAKE_SHOW_SECRETS=1 -- "${AK_PY}" "${ROOT}/lib/ak.py" claude-glm)"
  expect_line "the python loader reads KEY=value lines (export, quotes)" "${out}" "ANTHROPIC_AUTH_TOKEN=planted-quoted-0x1"
}
