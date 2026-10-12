# shellcheck shell=bash
# `ak capacity` (lib/capacity.py) and the usage cache (lib/state.py): the
# arithmetic, cap, cache and lease store are exercised bash free by
# tests/py/capacity_checks.py (Windows CI runs it natively); here the real
# launcher runs in a sandbox home against the loopback fake usage endpoint,
# including `--self` from inside a real `ak <kind> @profile` launch.

capacity_routes() {   # capacity_routes <5h-used-default> <5h-used-work>
  "${AK_PY}" - "${BOX}/routes.json" "$1" "$2" <<'PY'
import json, sys
path, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def c(u):
    return {"json": {"five_hour": {"utilization": u, "resets_at": "2099-01-01T00:00:00Z"},
                     "seven_day": {"utilization": 10, "resets_at": "2099-01-05T00:00:00Z"}}}
json.dump({"/claude": {"by_bearer": {"planted-cap-default-0x1": c(a), "planted-cap-work-0x1": c(b)}}}, open(path, "w"))
PY
}

scope_capacity() {
  py_checks capacity_checks.py

  local doc status out url schema="${ROOT}/docs/schema/capacity-v1.json" cache dir tok name
  box_new capacity claude opencode
  for name in default work; do
    case "${name}" in default) tok="planted-cap-default-0x1"; dir="${BOX}/home/.claude" ;;
      work) tok="planted-cap-work-0x1"; dir="${BOX}/home/.local/share/agentkit/profiles/claude/work" ;; esac
    mkdir -p "${dir}"
    printf '{"claudeAiOauth":{"accessToken":"%s","expiresAt":99999999999999,"scopes":["user:profile"],"subscriptionType":"max"}}' "${tok}" > "${dir}/.credentials.json"
  done
  capacity_routes 10 70
  usage_server_start "${BOX}/routes.json"
  url="AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://127.0.0.1:${USAGE_PORT}/claude"
  cache="${BOX}/home/.local/state/agentkit/usage-cache"

  # @work: 5h 70 used -> 30 free; 7d 10 used -> 80 free (reserve): headroom 30, ok.
  doc="${BOX}/capacity.json"
  ak_split "${url}" -- capacity claude @work --json; status=$?
  cp "${BOX}/out" "${doc}"
  expect_eq "capacity cli: a reading exits 0" "${status}" 0
  expect_eq "capacity json: matches docs/schema/capacity-v1.json" "$("${AK_PY}" "${ROOT}/tests/py/schema_check.py" "${schema}" "${doc}")" "valid"
  expect_eq "capacity json: headroom, binding window, verdict, live" \
    "$(json_get "${doc}" '[d["headroom_pct"], d["binding_window"], d["verdict"], d["source"], d["profile"]]')" '[30, "5h", "ok", "live", "@work"]'
  ak_split "${url}" -- capacity claude @work --low 30; status=$?
  expect_has "capacity cli: --low 30 makes 30% free low (text form)" "$(cat "${BOX}/out")" "claude @work  low  30% free"
  ak_split "${url}" AGENTKIT_CAPACITY_CRITICAL=30 AGENTKIT_CAPACITY_LOW=40 -- capacity claude @work --json
  expect_eq "capacity cli: AGENTKIT_CAPACITY_LOW/CRITICAL set the verdict" "$(json_get "${BOX}/out" 'd["verdict"]')" "critical"

  # The cache: the endpoint goes away, the reading stays (fresh, from cache).
  check "capacity cache: the reading was cached in a 0600 file" \
    bash -c '[[ -f "$1/claude@work.json" && "$(stat -c %a "$1/claude@work.json" 2>/dev/null || stat -f %Lp "$1/claude@work.json")" == 600 ]]' _ "${cache}"
  usage_server_stop
  ak_split "${url}" -- capacity claude @work --json; status=$?
  expect_eq "capacity cache: with the endpoint down a fresh cached reading answers" \
    "$(json_get "${BOX}/out" '[d["source"], d["headroom_pct"]]')" '["cache", 30]'
  ak_split "${url}" -- capacity claude @work --json --max-age 0; status=$?
  expect_eq "capacity cache: --max-age 0 reads live (endpoint down -> unknown, still exit 0)" \
    "${status}:$(json_get "${BOX}/out" '[d["source"], d["verdict"]]')" '0:["live", "unknown"]'

  # ak usage always reads live and refreshes the cache that capacity reads.
  capacity_routes 10 95
  usage_server_start "${BOX}/routes.json"
  url="AGENTKIT_USAGE_URL_ANTHROPIC_OAUTH=http://127.0.0.1:${USAGE_PORT}/claude"
  ak_split "${url}" -- capacity claude @work --json
  expect_eq "capacity cache: before ak usage the stale-but-fresh cached reading is reused" "$(json_get "${BOX}/out" 'd["headroom_pct"]')" "30"
  ak_split "${url}" -- usage claude --json
  ak_split "${url}" -- capacity claude @work --json
  expect_eq "capacity cache: ak usage refreshed it (95% used -> critical, from cache)" \
    "$(json_get "${BOX}/out" '[d["verdict"], d["headroom_pct"], d["source"]]')" '["critical", 5, "cache"]'

  # The drill cap lowers, never raises.
  ak_split "${url}" AGENTKIT_CAPACITY_CAP=@default=5 -- capacity claude --json
  expect_eq "capacity cap: @default capped at 5 reads critical and capped" \
    "$(json_get "${BOX}/out" '[d["verdict"], d["headroom_pct"], d["capped"]]')" '["critical", 5, true]'
  ak_split "${url}" AGENTKIT_CAPACITY_CAP=claude@work=60 -- capacity claude @work --json
  expect_eq "capacity cap: a cap above the real reading changes nothing" "$(json_get "${BOX}/out" 'd["headroom_pct"]')" "5"
  ak_split "${url}" AGENTKIT_CAPACITY_CAP=work=5 -- capacity claude @work; status=$?
  expect_eq "capacity cap: an invalid cap exits 2 (never runs uncapped)" "${status}" 2
  ak_split "${url}" AGENTKIT_CAPACITY_LOW=5 -- pick claude; status=$?
  expect_eq "capacity cap: a capacity-only threshold (LOW=5, no cap) never breaks ak pick" "${status}" 0
  ak_split "${url}" AGENTKIT_CAPACITY_CAP=claud@work=5 -- capacity claude @work; status=$?
  expect_eq "capacity cap: a mistyped CLI in the cap exits 2" "${status}" 2
  ak_split "${url}" AGENTKIT_CAPACITY_CAP=@default=0 -- pick claude --count 2 --json
  expect_eq "capacity cap: ak pick applies the same cap (@default at 0 is not chosen)" \
    "$(json_get "${BOX}/out" '[c["profile"] for c in d["chosen"]]')" '["@work"]'

  # --self: from inside a real launch; never a guess outside one.
  ak_split -- capacity --self; status=$?
  expect_eq "capacity self: outside an ak launch exits 3" "${status}" 3
  expect_has "capacity self: the refusal says unknown account" "$(cat "${BOX}/err")" "unknown account"
  cat > "${BOX}/bin/claude" <<EOF
#!/usr/bin/env bash
exec bash "${ROOT}/bin/ak" capacity --self --json
EOF
  chmod +x "${BOX}/bin/claude"
  box_posture ask
  ak_split "${url}" -- claude @work; status=$?
  expect_eq "capacity self: inside ak claude @work, --self reads that account" \
    "${status}:$(json_get "${BOX}/out" '[d["kind"], d["cli"], d["profile"], d["verdict"]]')" '0:["claude", "claude", "@work", "critical"]'
  ak_split "${url}" -- claude; status=$?
  expect_eq "capacity self: inside a bare ak claude (@default) --self works too" \
    "${status}:$(json_get "${BOX}/out" '[d["profile"], d["verdict"]]')" '0:["@default", "ok"]'
  ak_split "${url}" AGENTKIT_ACTIVE_ACCOUNT=claude/@ghost -- claude @work; status=$?
  expect_eq "capacity self: a launch overwrites an inherited marker" "$(json_get "${BOX}/out" 'd["profile"]')" "@work"
  cp "${FAKES}/claude" "${BOX}/bin/claude"
  out="$(ak -- claude @work)"
  expect_line "capacity self: the launch marker holds the kind and profile name only" "${out}" "AGENTKIT_ACTIVE_ACCOUNT=claude/@work"
  expect_line "capacity self: AGENTKIT_ACTIVE_PROFILE is unchanged" "${out}" "AGENTKIT_ACTIVE_PROFILE=claude/work"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/opencode/iso"
  out="$(ak AGENTKIT_ACTIVE_ACCOUNT=claude/@work -- profiles run opencode @iso -- env)"
  expect_line "capacity self: ak profiles run replaces an inherited marker" "${out}" "AGENTKIT_ACTIVE_ACCOUNT=opencode/@iso"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/codex/work"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/opencode/fresh/state"     # never launched: no mirror links
  ak XDG_STATE_HOME="${BOX}/home/.local/share/agentkit/profiles/opencode/fresh/state" -- lease codex @work --owner local:x:p1 >/dev/null
  check "capacity state: an XDG_STATE_HOME printed by ak env opencode keeps the lease store machine-wide" \
    bash -c '[[ -f "$1/leases/leases.json" && ! -e "$2" ]]' _ \
    "${BOX}/home/.local/state/agentkit" "${BOX}/home/.local/share/agentkit/profiles/opencode/fresh/state/agentkit"
  ak -- lease release codex @work --owner local:x:p1 >/dev/null
  out="$(ak XDG_STATE_HOME="${BOX}/custom-state" -- env opencode @iso)"
  expect_has "capacity state: with a custom XDG_STATE_HOME, ak env names AGENTKIT_STATE_DIR on stderr" "${out}" \
    "AGENTKIT_STATE_DIR=${BOX}/custom-state/agentkit"
  expect_lacks "capacity state: ... and its printed lines stay interface 1 (no AGENTKIT_STATE_DIR line)" \
    "$(ak_split XDG_STATE_HOME="${BOX}/custom-state" -- env opencode @iso; cat "${BOX}/out")" "AGENTKIT_STATE_DIR="
  out="$(ak -- env claude @work)"
  expect_lacks "capacity self: ak env never prints the internal marker" "${out}" "AGENTKIT_ACTIVE_ACCOUNT"
  mkdir -p "${BOX}/home/.local/share/agentkit/profiles/opencode/iso"
  out="$(ak -- opencode @iso)"
  expect_line "capacity state: an xdg-isolated launch keeps the kit state machine-wide" "${out}" \
    "AGENTKIT_STATE_DIR=${BOX}/home/.local/state/agentkit"
  box_posture ""

  # --self without any marker (a Codex tool shell run by its app-server daemon):
  # the CLI home variable that names a profile inside ak's own tree is the account.
  local proot="${BOX}/home/.local/share/agentkit/profiles"
  ak_split "${url}" CLAUDE_CONFIG_DIR="${proot}/claude/work" -- capacity --self --json; status=$?
  expect_eq "capacity self: no marker, CLAUDE_CONFIG_DIR=<profiles>/claude/work reads claude @work" \
    "${status}:$(json_get "${BOX}/out" '[d["cli"], d["profile"], d["verdict"]]')" '0:["claude", "@work", "critical"]'
  ak_split CODEX_HOME="${proot}/codex/work" -- capacity --self --json; status=$?
  expect_eq "capacity self: no marker, CODEX_HOME=<profiles>/codex/work names codex @work" \
    "${status}:$(json_get "${BOX}/out" '[d["cli"], d["profile"]]')" '0:["codex", "@work"]'
  ln -s "${proot}/codex/work" "${BOX}/codex-link"
  ak_split CODEX_HOME="${BOX}/codex-link" -- capacity --self --json; status=$?
  expect_eq "capacity self: a home reached through a symlink resolves to the profile" \
    "${status}:$(json_get "${BOX}/out" 'd["profile"]')" '0:@work'
  ak_split "${url}" AGENTKIT_ACTIVE_ACCOUNT=claude/@default CODEX_HOME="${proot}/codex/work" -- capacity --self --json
  expect_eq "capacity self: the launch marker wins over a home variable" "$(json_get "${BOX}/out" '[d["cli"], d["profile"]]')" '["claude", "@default"]'
  mkdir -p "${BOX}/home/.codex" "${BOX}/elsewhere/codex/work" "${proot}/codex/work/nested"
  ak_split CODEX_HOME="${BOX}/home/.codex" -- capacity --self; status=$?
  expect_eq "capacity self: the CLI's default home is never derived (exit 3)" "${status}" 3
  ak_split CODEX_HOME="${BOX}/elsewhere/codex/work" -- capacity --self; status=$?
  expect_eq "capacity self: a home outside ak's profile tree is never derived (exit 3)" "${status}" 3
  ak_split CODEX_HOME="${proot}/codex/work/nested" -- capacity --self; status=$?
  expect_eq "capacity self: a directory below a profile is not a profile (exit 3)" "${status}" 3
  ak_split CODEX_HOME="${proot}/claude/work" -- capacity --self; status=$?
  expect_eq "capacity self: another CLI's profile directory is not this CLI's account (exit 3)" "${status}" 3
  ak_split CODEX_HOME="${proot}/codex/work" CLAUDE_CONFIG_DIR="${proot}/claude/work" -- capacity --self; status=$?
  expect_eq "capacity self: two CLI homes in the tree are ambiguous (exit 3, never a guess)" "${status}" 3
  expect_has "capacity self: ... and the refusal names both" "$(cat "${BOX}/err")" "codex @work"

  # Secrecy: no token in any output or cache file.
  ak_split "${url}" -- capacity claude @work --json
  expect_lacks "capacity security: no token in stdout or stderr" "$(cat "${BOX}/out" "${BOX}/err")" "planted-cap"
  expect_lacks "capacity security: no token in any cache file" "$(cat "${cache}"/*.json)" "planted-cap"
  usage_server_stop

  ak_split -- capacity; status=$?
  expect_eq "capacity cli: no kind and no --self exits 2" "${status}" 2
  ak_split -- capacity claude @ghost; status=$?
  expect_eq "capacity cli: an account the kit cannot see exits 3" "${status}" 3
  out="$(ak -- capacity --help)"
  expect_has "capacity cli: --help states the cache rule" "${out}" "ak usage is the only command that"
  out="$(ak -- --help)"
  expect_has "capacity cli: ak --help lists ak capacity" "${out}" "ak capacity"
  check "capacity platform: lib/capacity.py, lib/state.py and lib/lease.py import nothing POSIX-only" \
    bash -c '! grep -Eq "import (fcntl|pwd|grp|termios|resource)|os\.fork|signal\.alarm|os\.getuid" "$1" "$2" "$3"' _ \
    "${ROOT}/lib/capacity.py" "${ROOT}/lib/state.py" "${ROOT}/lib/lease.py"
  check "capacity platform: CI runs capacity_checks.py natively on Windows" \
    bash -c 'grep -q "capacity_checks.py" "$1"' _ "${ROOT}/.github/workflows/ci.yml"
}
