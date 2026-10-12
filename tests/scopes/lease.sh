# shellcheck shell=bash
# `ak lease` and `ak pick --owner` (lib/lease.py, lib/pick.py) through the
# real launcher in a sandbox home. The store's rules (expiry, sweep, mutex,
# release by owner only) are covered bash free by tests/py/capacity_checks.py.

scope_lease() {
  local status out doc store url
  box_new lease claude codex
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/codex/work" "${BOX}/home/.local/share/agentkit/profiles/claude/work"
  store="${BOX}/home/.local/state/agentkit/leases/leases.json"

  ak_split -- lease codex @work --owner local:w1:p1 --ttl 90m --purpose "lane cak"; status=$?
  expect_eq "lease cli: a Codex lease exits 0" "${status}" 0
  expect_has "lease cli: it is exclusive" "$(cat "${BOX}/out")" "(exclusive)"
  ak_split -- lease codex @work --owner local:w1:p2; status=$?
  expect_eq "lease cli: a second owner on a Codex account exits 1" "${status}" 1
  expect_has "lease cli: the refusal names the holder" "$(cat "${BOX}/err")" "leased to local:w1:p1"
  ak_split -- lease codex @work --owner local:w1:p1; status=$?
  expect_has "lease cli: the same owner renews" "${status}:$(cat "${BOX}/out")" "0:renewed codex @work"
  ak_split -- lease claude @work --owner local:w1:p1; ak_split -- lease claude @work --owner local:w1:p2; status=$?
  expect_eq "lease cli: a Claude account takes several owners" "${status}" 0
  check "lease store: the store file is 0600" \
    bash -c '[[ "$(stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1")" == 600 ]]' _ "${store}"

  doc="${BOX}/leases.json"
  ak_split -- lease ls --json; cp "${BOX}/out" "${doc}"
  expect_eq "lease ls: --json matches docs/schema/leases-v1.json" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/leases-v1.json" "${doc}")" "valid"
  expect_eq "lease ls: three active leases, the Codex one exclusive" \
    "$(json_get "${doc}" '[(l["cli"], l["profile"], l["owner"], l["exclusive"]) for l in d["leases"]]')" \
    '[["codex", "@work", "local:w1:p1", true], ["claude", "@work", "local:w1:p1", false], ["claude", "@work", "local:w1:p2", false]]'
  out="$(ak -- lease ls)"
  expect_has "lease ls: text lists owner and purpose" "${out}" "local:w1:p1"

  ak_split -- lease release codex @work --owner local:w1:p2; status=$?
  expect_eq "lease release: another owner cannot release it (exit 1)" "${status}" 1
  ak_split -- lease release codex @work --owner local:w1:p1; status=$?
  expect_eq "lease release: the owner releases it" "${status}" 0
  ak_split -- lease codex @work --owner local:w1:p2; status=$?
  expect_eq "lease release: the account is free for the next owner" "${status}" 0

  # Contention between processes: six owners race for one Codex account; exactly one wins.
  ak_split -- lease release codex @work --owner local:w1:p2
  local i wins=0
  for i in 1 2 3 4 5 6; do
    ( ak -- lease codex @work --owner "local:race:p${i}" >/dev/null 2>&1; echo $? > "${BOX}/race.${i}" ) &
  done
  wait
  for i in 1 2 3 4 5 6; do [[ "$(cat "${BOX}/race.${i}")" == 0 ]] && wins=$((wins + 1)); done
  expect_eq "lease race: six concurrent owners, exactly one gets the Codex lease" "${wins}" 1
  expect_eq "lease race: the store holds exactly one Codex lease" \
    "$(ak -- lease ls --json | json_get - 'len([l for l in d["leases"] if l["cli"] == "codex"])')" 1
  check "lease race: no lock or stale lock is left behind" \
    bash -c '! ls -a "$1" | grep -q "^\.lock"' _ "$(dirname "${store}")"

  ak_split -- lease codex @ghost --owner local:w1:p1; status=$?
  expect_eq "lease cli: an account the kit cannot see exits 3" "${status}" 3
  ak_split -- lease codex @work --owner "bad owner"; status=$?
  expect_eq "lease cli: an invalid owner exits 2" "${status}" 2
  ak_split -- lease codex @work; status=$?
  expect_eq "lease cli: a missing --owner exits 2" "${status}" 2
  ak_split -- lease codex @work --owner a:b --ttl 2d; status=$?
  expect_eq "lease cli: a ttl over 24h exits 2" "${status}" 2
  ak_split -- lease codex @work --owner a:b --purpose "ghp_aaaaaaaaaaaaaaaaaaaaaaaa"; status=$?
  expect_eq "lease cli: a secret-shaped purpose exits 2" "${status}" 2
  expect_lacks "lease cli: the refused purpose is never echoed" "$(cat "${BOX}/out" "${BOX}/err")" "ghp_aaaa"
  expect_lacks "lease store: the refused purpose never reached the store" "$(cat "${store}")" "ghp_aaaa"
  out="$(ak -- lease --help)"
  expect_has "lease cli: --help prints the grammar" "${out}" "ak lease release"
  out="$(ak -- --help)"
  expect_has "lease cli: ak --help lists ak lease" "${out}" "ak lease"

  # pick --owner over real usage rows: @default 90 free, @work 70 free.
  local name dir tok
  for name in default work; do
    case "${name}" in default) tok="planted-lease-default-0x1"; dir="${BOX}/home/.claude" ;;
      work) tok="planted-lease-work-0x1"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/work" ;; esac
    mkdir -p "${dir}"
    printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${tok}" > "${dir}/.credentials.json"
  done
  "${AK_PY}" - "${BOX}/routes.json" <<'PY'
import json, sys
def c(u):
    return {"json": {"five_hour": {"utilization": u, "resets_at": "2099-01-01T00:00:00Z"},
                     "seven_day": {"utilization": 0, "resets_at": "2099-01-05T00:00:00Z"}}}
json.dump({"/claude": {"by_bearer": {"planted-lease-default-0x1": c(10), "planted-lease-work-0x1": c(30)}}}, open(sys.argv[1], "w"))
PY
  usage_server_start "${BOX}/routes.json"
  url="AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://127.0.0.1:${USAGE_PORT}/claude"
  ak_split -- lease claude @default --owner local:w2:p1
  ak_split -- lease claude @default --owner local:w2:p2
  ak_split "${url}" -- pick claude --count 2 --json
  expect_eq "pick owner: without --owner the ranking is v0.5's (@default 90 first), leases shown" \
    "$(json_get "${BOX}/out" '[(c["profile"], c["leases"]) for c in d["chosen"]]')" '[["@default", 2], ["@work", 2]]'
  doc="${BOX}/pick-owner.json"
  ak_split "${url}" -- pick claude --count 2 --owner local:w9:p9 --json; cp "${BOX}/out" "${doc}"
  expect_eq "pick owner: with equal leases by others, headroom decides (@default 90/3 before @work 70/3)" \
    "$(json_get "${doc}" '[c["profile"] for c in d["chosen"]]')" '["@default", "@work"]'
  ak_split -- lease release claude @work --owner local:w1:p1
  ak_split -- lease release claude @work --owner local:w1:p2
  ak_split "${url}" -- pick claude --count 2 --owner local:w9:p9 --json; cp "${BOX}/out" "${doc}"
  expect_eq "pick owner: two leases on @default (90/3 = 30) put the unleased @work (70) first" \
    "$(json_get "${doc}" '[c["profile"] for c in d["chosen"]]')" '["@work", "@default"]'
  expect_eq "pick owner: --owner --json matches pick-v1 and records the owner" \
    "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${ROOT}/docs/schema/pick-v1.json" "${doc}"):$(json_get "${doc}" 'd["owner"]')" "valid:local:w9:p9"
  ak_split "${url}" -- pick codex --owner "bad owner"; status=$?
  expect_eq "pick owner: an invalid --owner exits 2" "${status}" 2
  usage_server_stop
}
