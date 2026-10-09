# shellcheck shell=bash
# scripts/check-public-hygiene.sh: every rule fires on a planted violation,
# allowed addresses and allowlisted fixtures pass, output never echoes the
# matched text. Violations are assembled at run time ("Dai""lyBot") so this
# file itself stays clean.

hyg() {
  bash "${ROOT}/scripts/check-public-hygiene.sh" --root "$1" 2>&1
}

scope_hygiene() {
  local d out status rule text
  local u="/Us""ers/jane" org="Dai""lyBot-Inc" repo="dailybot""-core" mesh="[dailybot""-mesh]"
  local aws gh llm slack goog pkey mail quoted
  aws="AK""IA$(printf 'A%.0s' {1..16})"
  gh="gh""p_$(printf 'a%.0s' {1..36})"
  llm="sk-""ant-$(printf 'b%.0s' {1..30})"
  slack="xo""xb-1234567890-abcdefgh"
  goog="AI""za$(printf 'c%.0s' {1..35})"
  pkey="-----BEGIN RSA PRI""VATE KEY-----"
  mail="jane.doe""@dailybot.com"
  quoted="api_key = \"$(printf 'Z%.0s' {1..24})\""

  out="$(hyg "${ROOT}")"; status=$?
  expect_eq "the repository's tracked files are clean" "${status}" 0

  local -a cases=(
    "personal-path|cd ${u}/projects"
    "personal-path|cd /ho""me/jane/src"
    "private-org|see ${org} on GitHub"
    "private-repo|clone ${repo} first"
    "internal-name|stamp ${mesh}"
    "internal-name|run db""dev up"
    "email|mail ${mail}"
    "aws-key|${aws}"
    "github-token|${gh}"
    "llm-key|${llm}"
    "slack-token|${slack}"
    "google-key|${goog}"
    "private-key|${pkey}"
    "quoted-secret|${quoted}"
  )
  for c in "${cases[@]}"; do
    rule="${c%%|*}"; text="${c#*|}"
    d="${SANDBOX}/hyg-${rule}-$RANDOM"
    mkdir -p "${d}"
    printf '%s\n' "${text}" > "${d}/file.md"
    out="$(hyg "${d}")"; status=$?
    if [[ "${status}" -eq 1 && "${out}" == *"HIT ${rule}"*"file.md:1"* ]]; then
      pass "rule ${rule} fires on a planted violation"
    else
      fail "rule ${rule} did not fire (exit ${status}): ${out}"
    fi
    if [[ "${rule}" != personal-path && "${rule}" != private-org && "${rule}" != private-repo && "${rule}" != internal-name && "${out}" == *"${text}"* ]]; then
      fail "rule ${rule}: the output echoed the matched text"
    fi
  done
  d="${SANDBOX}/hyg-noecho"; mkdir -p "${d}"; printf '%s\n' "${gh}" > "${d}/a.txt"
  expect_lacks "a hit never prints the matched secret" "$(hyg "${d}")" "${gh}"

  d="${SANDBOX}/hyg-mail-ok"; mkdir -p "${d}"
  printf 'write to security''@dailybot.com, support''@dailybot.com, ops''@dailybot.com or conduct''@dailybot.com\n' > "${d}/a.md"
  hyg "${d}" >/dev/null; expect_eq "security@/support@/ops@/conduct@ addresses are allowed" "$?" 0
  d="${SANDBOX}/hyg-word"; mkdir -p "${d}"
  printf 'my-api-services-client and dbdevices are other words\n' > "${d}/a.md"
  hyg "${d}" >/dev/null; expect_eq "names inside other words are not flagged" "$?" 0

  d="${SANDBOX}/hyg-allow"; mkdir -p "${d}/tests"
  printf 'token = "planted-%s"\n' "$(printf 'q%.0s' {1..20})" > "${d}/tests/fixture.sh"
  hyg "${d}" >/dev/null; expect_eq "an unlisted fake-looking fixture still fails" "$?" 1
  printf 'tests/*.sh | quoted-secret | planted parser fixture\n' > "${d}/.public-hygiene-allow"
  out="$(hyg "${d}")"; status=$?
  expect_eq "a listed, visibly fake fixture passes" "${status}:$(grep -c '1 allowlisted' <<<"${out}")" "0:1"
  printf 'token = "%s"\n' "$(printf 'r%.0s' {1..20})" > "${d}/tests/real.sh"
  hyg "${d}" >/dev/null; expect_eq "the allowlist never covers a line without fake/test/planted/example" "$?" 1

  d="${SANDBOX}/hyg-vendored"; mkdir -p "${d}/.agents/skills/x"
  printf '%s\n' "${org}" > "${d}/.agents/skills/x/SKILL.md"
  hyg "${d}" >/dev/null; expect_eq "vendored .agents/skills copies are not scanned" "$?" 0
  check "the hygiene script is wired into CI" grep -q 'scripts/check-public-hygiene.sh' "${ROOT}/.github/workflows/ci.yml"
}
