# shellcheck shell=bash
# update.sh — ak update offline: discovery, verification, shadowed installs,
# take-over of vendor-managed links, the re-pin and its rollback. A fake
# curl serves fixture documents (registry, channel, manifest, artifacts) by
# URL; a fake npm answers `config get prefix` and really installs a served
# tarball into a sandbox prefix. Every check runs the INSTALLED copy, so the
# re-pin writes into the sandbox (bin/ak derives its providers.toml root
# from its own location), never into the repository.

# fake_curl serving ${FAKE_NET_DIR}/<url with / -> _> when present, tampered
# bytes otherwise; fake_npm answering `config get prefix` and installing a
# tarball's package/bin into ${FAKE_NPM_PREFIX}/bin.
update_fakes() {
  cat > "${BOX}/bin/curl" <<'EOF'
#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    *://*) url="$1" ;;
  esac
  shift
done
f="${FAKE_NET_DIR}/$(printf %s "$url" | tr '/' '_')"
if [ -f "${f}" ]; then cp "${f}" "${out}"; else printf 'tampered bytes for %s\n' "${url}" > "${out}"; fi
echo "CURL ${url}" >> "${FAKE_NET_LOG}"
exit 0
EOF
  cat > "${BOX}/bin/npm" <<'EOF'
#!/bin/sh
echo "NPM $*" >> "${FAKE_NET_LOG}"
if [ "$1" = "config" ]; then echo "${FAKE_NPM_PREFIX}"; exit 0; fi
if [ "$1" = "install" ]; then
  tgz=""
  for a in "$@"; do case "$a" in *.tgz) tgz="$a" ;; esac; done
  [ -z "$tgz" ] && exit 1
  tmp="$(mktemp -d)"
  tar -xzf "$tgz" -C "$tmp" || { rm -rf "$tmp"; exit 1; }
  mkdir -p "${FAKE_NPM_PREFIX}/bin"
  cp -R "$tmp"/package/bin/. "${FAKE_NPM_PREFIX}/bin/" || { rm -rf "$tmp"; exit 1; }
  chmod -R +x "${FAKE_NPM_PREFIX}/bin" 2>/dev/null
  rm -rf "$tmp"
  exit 0
fi
exit 0
EOF
  chmod +x "${BOX}/bin/curl" "${BOX}/bin/npm"
}

scope_update() {
  local out status intg sha plat
  box_new update claude codex
  local dest="${BOX}/home/.local/share/agentkit"
  export FAKE_NET_DIR="${BOX}/net" FAKE_NET_LOG="${BOX}/net.log" FAKE_NPM_PREFIX="${BOX}/home/.npm-prefix"
  mkdir -p "${FAKE_NET_DIR}" "${FAKE_NPM_PREFIX}" "${BOX}/build/package/bin" \
    "${BOX}/vendor/codex-standalone/current/bin" "${BOX}/vendor/claude-native/2.1.325"
  # The fixture path for a URL, exactly the way the fake curl derives it.
  netfile() { printf '%s/%s' "${FAKE_NET_DIR}" "$(printf %s "$1" | tr '/' '_')"; }
  # A pinned field from a providers.toml (version, or a sha256 platform).
  field_of() {
    python3 - "$1" "$2" "$3" "${ROOT}" <<'PY'
import sys
path, cli, key, root = sys.argv[1:5]
try:
    import tomllib as toml
    doc = toml.load(open(path, "rb"))
except ImportError:
    sys.path.insert(0, root + "/lib")
    import tomlmini
    doc = tomlmini.loads(open(path).read())
value = doc["clis"][cli]["install"][key]
if isinstance(value, dict):
    value = value[sys.argv[4] and "linux-x64"]
print(value)
PY
  }
  local pin0
  pin0="$(field_of "${ROOT}/providers.toml" codex version)"
  local claude_sha0
  claude_sha0="$(field_of "${ROOT}/providers.toml" claude sha256)"
  update_fakes

  # The kit, installed once; every ak below is the installed copy.
  box_run -- bash "${ROOT}/install.sh" --no-rc > /dev/null 2>&1
  # PATH for the installed copy: the box fakes first, then its ~/.local/bin
  # (the binary channel's install target).
  local UP_PATH="${BOX}/bin:${BOX}/home/.local/bin"
  ak_up() {
    local -a envs=()
    while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
    [[ "${1:-}" == "--" ]] && shift
    ( cd "${BOX}/work" && env -i HOME="${BOX}/home" PATH="${UP_PATH}:${BASE_PATH}" \
        TMPDIR="${BOX}/tmp" AGENTKIT_KEYCHAIN=off \
        FAKE_NET_DIR="${FAKE_NET_DIR}" FAKE_NET_LOG="${FAKE_NET_LOG}" FAKE_NPM_PREFIX="${FAKE_NPM_PREFIX}" \
        ${envs[@]+"${envs[@]}"} "${dest}/bin/ak" "$@" </dev/null >"${BOX}/out" 2>"${BOX}/err" )
  }

  # Fixtures. codex: registry doc (9.9.9) + a real tarball whose integrity
  # matches it. claude: a channel file (9.8.7), a manifest naming a digest
  # for every platform token, and the same artifact for each platform URL.
  printf '#!/bin/sh\necho 0.166.0\n' > "${BOX}/vendor/codex-standalone/current/bin/codex"
  printf '#!/bin/sh\necho 9.9.9\n' > "${BOX}/build/package/bin/codex"
  printf '{"name":"@openai/codex","version":"1.0.0"}\n' > "${BOX}/build/package/package.json"
  chmod +x "${BOX}/vendor/codex-standalone/current/bin/codex" "${BOX}/build/package/bin/codex"
  tar -cf - -C "${BOX}/build" package | gzip -n > "$(netfile 'https://registry.npmjs.org/@openai/codex/-/codex-9.9.9.tgz')"
  intg="$(python3 -c "import hashlib,base64,sys; print('sha512-'+base64.b64encode(hashlib.sha512(open(sys.argv[1],'rb').read()).digest()).decode())" \
    "$(netfile 'https://registry.npmjs.org/@openai/codex/-/codex-9.9.9.tgz')")"
  printf '{"version":"9.9.9","dist":{"integrity":"%s"}}\n' "${intg}" \
    > "$(netfile 'https://registry.npmjs.org/@openai/codex/latest')"
  printf '#!/bin/sh\necho "9.8.7 (Claude Code)"\n' > "${BOX}/build/claude-artifact"
  chmod +x "${BOX}/build/claude-artifact"
  sha="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "${BOX}/build/claude-artifact")"
  for plat in linux-x64 linux-arm64 darwin-x64 darwin-arm64; do
    cp "${BOX}/build/claude-artifact" "$(netfile "https://downloads.claude.ai/claude-code-releases/9.8.7/${plat}/claude")"
  done
  printf '{"platforms":{"linux-x64":{"checksum":"%s"},"linux-arm64":{"checksum":"%s"},"darwin-x64":{"checksum":"%s"},"darwin-arm64":{"checksum":"%s"}}}\n' \
    "${sha}" "${sha}" "${sha}" "${sha}" \
    > "$(netfile 'https://downloads.claude.ai/claude-code-releases/9.8.7/manifest.json')"
  printf '9.8.7\n' > "$(netfile 'https://downloads.claude.ai/claude-code-releases/latest')"
  # The vendor-managed machine: a standalone codex and a native claude, both
  # links ak did not make, both winners on PATH.
  printf '#!/bin/sh\necho "2.1.325 (Claude Code)"\n' > "${BOX}/vendor/claude-native/2.1.325/claude"
  chmod +x "${BOX}/vendor/claude-native/2.1.325/claude"
  rm -f "${BOX}/bin/codex"
  ln -s "${BOX}/vendor/codex-standalone/current/bin/codex" "${BOX}/bin/codex"
  mkdir -p "${BOX}/home/.local/bin"
  ln -s "${BOX}/vendor/claude-native/2.1.325/claude" "${BOX}/home/.local/bin/claude"

  # --- codex: the shadowed install (the bug this command exists for) -------
  ak_up -- update codex; status=$?
  out="$(cat "${BOX}/out")"
  expect_eq "codex shadowed install is reported skipped" "${status}" 3
  expect_has "the note names the shadowed winner" "${out}" "installed 9.9.9, but PATH still resolves 0.166.0"
  expect_has "the note offers --take-over" "${out}" "rerun with --take-over"
  check "the pin did not move" test "$(field_of "${dest}/providers.toml" codex version)" = "${pin0}"
  check "no backup was made for a refused update" test ! -e "${dest}/providers.toml.bak"
  expect_eq "the vendor link is untouched" "$(readlink "${BOX}/bin/codex")" "${BOX}/vendor/codex-standalone/current/bin/codex"
  check "the registry document was fetched" grep -q 'registry.npmjs.org/@openai/codex/latest' "${FAKE_NET_LOG}"
  check "the tarball was downloaded and handed to npm" grep -q 'NPM install -g' "${FAKE_NET_LOG}"

  # --- codex: a tampered artifact refuses before anything moves -----------
  printf 'tampered tarball bytes\n' > "$(netfile 'https://registry.npmjs.org/@openai/codex/-/codex-9.9.9.tgz')"
  ak_up -- update codex --take-over; status=$?
  out="$(cat "${BOX}/out")"
  expect_eq "a tampered tarball fails the update" "${status}" 3
  expect_has "the failure says the pin is unchanged" "${out}" "the pin is unchanged"
  check "the pin still did not move" test "$(field_of "${dest}/providers.toml" codex version)" = "${pin0}"
  expect_eq "the vendor link survived the failed verify" "$(readlink "${BOX}/bin/codex")" "${BOX}/vendor/codex-standalone/current/bin/codex"

  # --- codex: the take-over lands the verified release and moves the pin --
  tar -cf - -C "${BOX}/build" package | gzip -n > "$(netfile 'https://registry.npmjs.org/@openai/codex/-/codex-9.9.9.tgz')"
  ak_up -- update codex --take-over; status=$?
  out="$(cat "${BOX}/out")"
  expect_eq "the taken-over update succeeds" "${status}" 0
  expect_has "codex is updated" "${out}" "updated  9.9.9"
  expect_eq "PATH now resolves the fresh copy through a link" "$(readlink "${BOX}/bin/codex")" "${FAKE_NPM_PREFIX}/bin/codex"
  expect_eq "the resolved codex is 9.9.9" "$(box_run -- "${FAKE_NPM_PREFIX}/bin/codex" --version)" "9.9.9"
  check "the pin moved to 9.9.9" grep -q 'version = "9.9.9"' "${dest}/providers.toml"
  check "the fetched integrity re-pinned" grep -q "\"${intg}\"" "${dest}/providers.toml"
  check "the previous providers.toml is kept" grep -q "version = \"${pin0}\"" "${dest}/providers.toml.bak"

  # --- codex: current, and one JSON document ------------------------------
  ak_up -- update codex --json; status=$?
  expect_eq "a second run is current" "${status}" 0
  expect_eq "the JSON surface parses (update-v1, current)" \
    "$(json_get "${BOX}/out" 'd["schema"]')+$(json_get "${BOX}/out" 'd["results"][0]["status"]')+$(json_get "${BOX}/out" 'd["results"][0]["pin_written"]')" \
    "update-v1+current+false"
  expect_eq "the JSON document is the only stdout" "$(head -c 1 "${BOX}/out")" "{"

  # --- codex: the no-install path re-pins only after verifying -------------
  # A vendor self-update outran the pin: the machine runs 9.9.9 while
  # providers.toml says 9.8.8. The catch-up run must download the vendor's
  # artifact and see it match the fetched digests BEFORE the pin moves —
  # a re-pin of unchecked network data would be trust without verification.
  python3 - "${dest}/providers.toml" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
assert 'version = "9.9.9"' in s
open(p, "w").write(s.replace('version = "9.9.9"', 'version = "9.8.8"', 1))
PY
  ak_up -- update codex --json; status=$?
  expect_eq "the catch-up re-pin succeeds" "${status}" 0
  expect_eq "the no-install run verifies then re-pins" \
    "$(json_get "${BOX}/out" 'd["results"][0]["status"]')+$(json_get "${BOX}/out" 'd["results"][0]["pin_written"]')" \
    "current+true"
  check "the pin moved to the verified release" grep -q 'version = "9.9.9"' "${dest}/providers.toml"

  # --- the pin lock: a fresh lock refuses, a stale one is reclaimed --------
  : > "${dest}/providers.toml.lock"
  ak_up -- update codex; status=$?
  expect_eq "a fresh pin lock refuses the update" "${status}" 3
  expect_has "the lock refusal names the lock" "$(cat "${BOX}/err")" "holds the pin lock"
  touch -t 202601010000 "${dest}/providers.toml.lock"
  ak_up -- update codex; status=$?
  expect_eq "a stale pin lock is reclaimed" "${status}" 0
  check "the reclaimed lock is cleaned up" test ! -e "${dest}/providers.toml.lock"

  # --- codex: network values that are not plain data refuse everything -----
  python3 - "$(netfile 'https://registry.npmjs.org/@openai/codex/latest')" <<'PY'
import json, sys
doc = {"version": "9.9.9",
       "dist": {"integrity": 'sha512-AAA"\nnpm_args = ["--registry=https://attacker.invalid"]'}}
json.dump(doc, open(sys.argv[1], "w"))
PY
  ak_up -- update codex --take-over; status=$?
  expect_eq "an injecting integrity is refused" "${status}" 3
  expect_has "the refusal names the bad value" "$(cat "${BOX}/out")" "not sha512-<base64>"
  check "providers.toml carries no injected configuration" bash -c "! grep -q 'attacker.invalid' '${dest}/providers.toml'"
  check "the pin survived the injection attempt" grep -q 'version = "9.9.9"' "${dest}/providers.toml"
  expect_eq "the vendor link survived the injection attempt" "$(readlink "${BOX}/bin/codex")" "${FAKE_NPM_PREFIX}/bin/codex"

  # --- codex: downgrades are refused --------------------------------------
  printf '{"version":"9.5.0","dist":{"integrity":"sha512-notused"}}\n' \
    > "$(netfile 'https://registry.npmjs.org/@openai/codex/latest')"
  printf '{"version":"9.5.0","dist":{"integrity":"sha512-notused"}}\n' \
    > "$(netfile 'https://registry.npmjs.org/@openai/codex/9.5.0')"
  ak_up -- update codex; status=$?
  expect_eq "a discovery older than the pin is refused" "${status}" 3
  expect_has "the pin-downgrade refusal is explained" "$(cat "${BOX}/out")" "refusing a downgrade: the pin (9.9.9) is newer than 9.5.0"
  ak_up -- update codex --version 9.5.0; status=$?
  expect_eq "a named downgrade still respects the machine" "${status}" 3
  expect_has "the machine-downgrade refusal is explained" "$(cat "${BOX}/out")" "PATH already resolves 9.9.9, newer than 9.5.0"
  check "the pin survived both refusals" grep -q 'version = "9.9.9"' "${dest}/providers.toml"

  # --- claude: a manifest missing a platform refuses before installing ----
  python3 - <<'PY'
import json, pathlib
p = pathlib.Path(__import__("os").environ.get("BOX", "")) if False else None
PY
  slug_manifest="$(netfile 'https://downloads.claude.ai/claude-code-releases/9.8.7/manifest.json')"
  python3 - "$slug_manifest" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
del doc["platforms"]["linux-arm64"]
json.dump(doc, open(sys.argv[1], "w"))
PY
  ak_up -- update claude --take-over; status=$?
  expect_eq "a manifest missing a platform fails the update" "${status}" 3
  expect_has "the missing platform is named" "$(cat "${BOX}/out")" "no digest for linux-arm64"
  check "nothing was installed for the refused manifest" test ! -e "${BOX}/home/.local/bin/claude.agentkit-orig"
  expect_eq "claude's link is untouched" "$(readlink "${BOX}/home/.local/bin/claude")" "${BOX}/vendor/claude-native/2.1.325/claude"

  # --- claude: the vendor link needs --take-over --------------------------
  python3 - "$slug_manifest" "${sha}" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for t in ("linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64"):
    doc["platforms"][t] = {"checksum": sys.argv[2]}
json.dump(doc, open(sys.argv[1], "w"))
PY
  ak_up -- update claude; status=$?
  expect_eq "claude's vendor link is refused without --take-over" "${status}" 3
  expect_has "the refusal names the link and its target" "$(cat "${BOX}/out")" "is a link ak did not make"
  ak_up -- update claude --take-over; status=$?
  out="$(cat "${BOX}/out")"
  expect_eq "the taken-over claude update succeeds" "${status}" 0
  expect_has "claude is updated" "${out}" "claude      updated  9.8.7"
  check "the link became a regular kit binary" test -f "${BOX}/home/.local/bin/claude" -a ! -L "${BOX}/home/.local/bin/claude"
  expect_eq "the resolved claude is 9.8.7" "$(box_run -- "${BOX}/home/.local/bin/claude" --version)" "9.8.7 (Claude Code)"
  check "the pin moved to 9.8.7" grep -q 'version = "9.8.7"' "${dest}/providers.toml"
  check "the manifest digests re-pinned under the kit's platform names" \
    grep -q "macos-arm64 = \"${sha}\"" "${dest}/providers.toml"
  check "the old claude digest is gone" bash -c "! grep -q '${claude_sha0}' '${dest}/providers.toml'"

  # --- claude: a foreign regular file is backed up, never deleted ---------
  cp "${BOX}/vendor/claude-native/2.1.325/claude" "${BOX}/home/.local/bin/claude"
  ak_up -- update claude; status=$?
  expect_eq "the regular-file replacement succeeds with a backup" "${status}" 0
  expect_eq "the previous binary is kept" "$(box_run -- "${BOX}/home/.local/bin/claude.agentkit-orig" --version)" "2.1.325 (Claude Code)"
  expect_eq "and the new one resolves" "$(box_run -- "${BOX}/home/.local/bin/claude" --version)" "9.8.7 (Claude Code)"

  # --- the update-v1 schema travels with the code -------------------------
  check "docs/schema/update-v1.json parses and names the surface" python3 -c "
import json, sys
doc = json.load(open('${ROOT}/docs/schema/update-v1.json'))
assert doc['properties']['schema']['const'] == 'update-v1'
assert 'results' in doc['properties']
"
}
