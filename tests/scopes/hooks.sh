# shellcheck shell=bash
# `ak profiles hooks <cli> @name`: Herdr's state hooks copied into a profile,
# registrations merged with paths rewritten, the real home never written.

# Fixtures shaped like `herdr integration install <cli>` leaves them.
hooks_fixtures() {
  local h="${BOX}/home"
  mkdir -p "${h}/.claude/hooks" "${h}/.codex" "${h}/.cursor" "${h}/.config/opencode/plugins" \
    "${h}/.pi/agent/extensions" "${h}/.grok/hooks"
  for f in "${h}/.claude/hooks/herdr-agent-state.sh" "${h}/.codex/herdr-agent-state.sh" \
      "${h}/.cursor/herdr-agent-state.sh" "${h}/.grok/hooks/herdr-agent-state.sh"; do
    printf '#!/bin/sh\n# installed by herdr\nexit 0\n' > "${f}"
    chmod 755 "${f}"
  done
  printf '// herdr plugin\n' > "${h}/.config/opencode/plugins/herdr-agent-state.js"
  printf '// herdr extension\n' > "${h}/.pi/agent/extensions/herdr-agent-state.ts"
  cat > "${h}/.claude/settings.json" <<JSON
{"model": "real-home-model", "hooks": {"SessionStart": [
  {"matcher": "^(startup|resume)$", "hooks": [{"type": "command", "command": "bash '${h}/.claude/hooks/herdr-agent-state.sh' session", "timeout": 10}]},
  {"hooks": [{"type": "command", "command": "echo my-own-real-home-hook"}]}
]}}
JSON
  printf '{"hooks":{"SessionStart":[{"hooks":[{"command":"bash '"'"'%s/.codex/herdr-agent-state.sh'"'"' session","timeout":10,"type":"command"}]}]}}\n' "${h}" > "${h}/.codex/hooks.json"
  printf '{"hooks":{"sessionStart":[{"command":"bash '"'"'%s/.cursor/herdr-agent-state.sh'"'"' session"}]},"version":1}\n' "${h}" > "${h}/.cursor/hooks.json"
  printf '{"hooks":{"SessionStart":[{"hooks":[{"command":"sh '"'"'%s/.grok/hooks/herdr-agent-state.sh'"'"' session","timeout":10,"type":"command"}]}]}}\n' "${h}" > "${h}/.grok/hooks/herdr.json"
}

real_home_digest() {
  ( cd "${BOX}/home" && find .claude .codex .cursor .config/opencode .pi .grok -type f -exec cksum {} + | sort )
}

scope_hooks() {
  local out status root before c p
  box_new hooks
  hooks_fixtures
  root="${BOX}/home/.local/share/agentkit/profiles"
  mkdir -p "${root}"/{claude,codex,cursor,opencode,pi,cline,grok}/work
  printf '{"model": "work-model", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo profile-own-hook"}]}]}}\n' \
    > "${root}/claude/work/settings.json"
  before="$(real_home_digest)"

  ak_split -- doctor --json
  expect_eq "doctor reports the hooks absent in a fresh profile" "$(json_get "${BOX}/out" 'd["herdr_hooks"]["claude"]')" '{"@default": "present", "@work": "absent"}'

  for c in claude codex cursor opencode pi grok; do
    out="$(ak -- profiles hooks "${c}" @work)"; status=$?
    expect_eq "ak profiles hooks ${c} @work exits 0" "${status}" 0
  done
  check "claude: the hook script is in the profile" test -x "${root}/claude/work/hooks/herdr-agent-state.sh"
  check "codex: the hook script is in the profile" test -x "${root}/codex/work/herdr-agent-state.sh"
  check "cursor: the hook script is in the profile's own .cursor" test -x "${root}/cursor/work/home/.cursor/herdr-agent-state.sh"
  check "opencode: the plugin is in the profile's config" test -f "${root}/opencode/work/config/opencode/plugins/herdr-agent-state.js"
  check "pi: the extension is in the profile" test -f "${root}/pi/work/extensions/herdr-agent-state.ts"
  check "grok: the hook and its registration are in the profile" test -x "${root}/grok/work/hooks/herdr-agent-state.sh" -a -f "${root}/grok/work/hooks/herdr.json"
  expect_eq "the hook script keeps its mode" "$(file_mode "${root}/claude/work/hooks/herdr-agent-state.sh")" 755

  p="${root}/claude/work/settings.json"
  expect_eq "claude: the registration points at the profile's copy" \
    "$(json_get "${p}" 'd["hooks"]["SessionStart"][0]["hooks"][0]["command"]')" "bash '${root}/claude/work/hooks/herdr-agent-state.sh' session"
  expect_eq "claude: the matcher is kept" "$(json_get "${p}" 'd["hooks"]["SessionStart"][0]["matcher"]')" '^(startup|resume)$'
  expect_eq "claude: the profile's own settings and hooks are kept" "$(json_get "${p}" '[d["model"], d["hooks"]["Stop"][0]["hooks"][0]["command"]]')" '["work-model", "echo profile-own-hook"]'
  expect_eq "claude: the real home's other hooks and settings are not copied" "$(json_get "${p}" '["my-own" in str(d), "real-home-model" in str(d)]')" '[false, false]'
  expect_eq "codex: hooks.json registered with the profile path" \
    "$(json_get "${root}/codex/work/hooks.json" 'd["hooks"]["SessionStart"][0]["hooks"][0]["command"]')" "bash '${root}/codex/work/herdr-agent-state.sh' session"
  expect_eq "cursor: hooks.json registered, version kept" \
    "$(json_get "${root}/cursor/work/home/.cursor/hooks.json" '[d["hooks"]["sessionStart"][0]["command"], d["version"]]')" \
    "[\"bash '${root}/cursor/work/home/.cursor/herdr-agent-state.sh' session\", 1]"
  check "grok: the copied registration points at the profile" grep -q "${root}/grok/work/hooks/herdr-agent-state.sh" "${root}/grok/work/hooks/herdr.json"
  if grep -rq "${BOX}/home/\.\(claude\|codex\|cursor\|grok\)/" "${root}"/*/work/settings.json "${root}"/*/work/hooks.json \
      "${root}/cursor/work/home/.cursor/hooks.json" "${root}/grok/work/hooks/herdr.json" 2>/dev/null; then
    fail "a profile registration still points into the real home"
  else pass "no profile registration points into the real home"; fi
  expect_eq "the real home is byte-identical (read, never written)" "$(real_home_digest)" "${before}"

  out="$(ak -- profiles hooks claude @work)"
  expect_has "running it again is a no-op" "${out}" "already has Herdr's hooks"
  expect_eq "the registration is not duplicated" "$(json_get "${p}" 'len(d["hooks"]["SessionStart"])')" 1
  ak_split -- doctor --json
  expect_eq "doctor reports the hooks present in the profile" "$(json_get "${BOX}/out" 'd["herdr_hooks"]["claude"]["@work"]')" present
  expect_eq "doctor reports every hooked profile" "$(json_get "${BOX}/out" 'sorted(c for c, v in d["herdr_hooks"].items() if v.get("@work") == "present")')" \
    '["claude", "codex", "cursor", "grok", "opencode", "pi"]'

  # Refusals.
  out="$(ak -- profiles hooks cline @work)"; status=$?
  expect_has "cline has no Herdr integration: usage error" "${status}:${out}" "2:ak: Herdr has no state-hook integration for cline"
  out="$(ak -- profiles hooks claude @default)"; status=$?
  expect_has "@default is refused (Herdr installs there itself)" "${status}:${out}" "2:ak: @default is the CLI's own home"
  out="$(ak -- profiles hooks claude @ghost)"; status=$?
  expect_eq "a missing profile exits 3" "${status}" 3
  out="$(ak -- profiles hooks claude)"; status=$?
  expect_eq "a missing @name is a usage error" "${status}" 2
  mkdir -p "${root}/claude/broken"
  printf '{not json' > "${root}/claude/broken/settings.json"
  out="$(ak -- profiles hooks claude @broken)"; status=$?
  expect_eq "an unparsable profile settings.json is refused and left untouched" "${status}:$(cat "${root}/claude/broken/settings.json")" "3:{not json"
  box_new hooks-none
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/codex/work"
  out="$(ak -- profiles hooks codex @work)"; status=$?
  expect_has "without Herdr's own install it exits 3 naming herdr integration install" "${status}:${out}" "herdr integration install codex"
  ak_split -- doctor --json
  expect_eq "a machine without Herdr hooks reports them absent" "$(json_get "${BOX}/out" 'd["herdr_hooks"]["codex"]')" '{"@default": "absent", "@work": "absent"}'
}
