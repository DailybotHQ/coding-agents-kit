#!/usr/bin/env bash
# Public-hygiene check: this repository is public, so no tracked file may
# carry private context or anything secret-shaped.
#
#   scripts/check-public-hygiene.sh [--root DIR]
#
# Scans tracked files (`git ls-files`; every file when DIR is not a git
# checkout), except vendored `.agents/skills/` copies and this check's own
# two files. Fails on: personal absolute paths, the private organisation,
# private repository names, internal tooling and mesh names, @dailybot.com
# addresses other than security@ / support@ / ops@ / conduct@, and secret
# patterns (AWS, GitHub, OpenAI/Anthropic/xAI, Slack, Google, private-key
# headers, quoted secret assignments of 16+ characters).
#
# A deliberate fixture is allowed only through `.public-hygiene-allow`
# (`<path> | <rule> | <reason>`), and only on a line that is visibly fake:
# it must contain `fake`, `test`, `planted` or `example`.
#
# Output names the rule and file:line only — never the matched text, which
# could itself be a secret. bash + grep, no network. Exit 1 on any hit.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--root" ]]; then
  ROOT="$(cd "${2:?--root needs a directory}" && pwd)"
fi
ALLOW="${ROOT}/.public-hygiene-allow"
SELF="scripts/check-public-hygiene.sh"

# rule-id|extended regex (grep -E); `i:` prefix = case-insensitive.
RULES=(
  'personal-path|/Users/[A-Za-z][A-Za-z0-9._-]*|/home/[a-z][a-z0-9_-]*/|[A-Za-z]:\\Users\\[A-Za-z]'
  'private-org|i:dailybot-inc'
  'private-repo|(^|[^A-Za-z0-9_-])(dailybot-core|coding-agent-host-kit|dailybot-private-skills|api-services|chatbot-functions|discord-gateway|msteams-app-manifesto|labs-projects)([^A-Za-z0-9_-]|$)'
  'internal-name|(^|[^A-Za-z0-9_-])(dbdev|dailybot-dev|dailybot-peers|dailybot-workspaces)([^A-Za-z0-9_-]|$)|dailybot-ws-|dailybot-mesh'
  'email|i:[A-Za-z0-9._%+-]+@dailybot\.com'
  'aws-key|(AKIA|ASIA)[0-9A-Z]{16}'
  'github-token|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}'
  'llm-key|sk-(proj-|ant-)?[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}'
  'slack-token|xox[abpors]-[A-Za-z0-9-]{10,}'
  'google-key|AIza[0-9A-Za-z_-]{35}'
  'private-key|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----'
  'quoted-secret|i:(api[_-]?key|secret|token|passw(or)?d)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'[:space:]]{16,}["'"'"']'
)
ALLOWED_EMAILS='^(security|support|ops|conduct)@dailybot\.com$'

cd "${ROOT}" || exit 2
FILES=()
if git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  while IFS= read -r -d '' f; do FILES+=("${f}"); done < <(git ls-files -z)
else
  while IFS= read -r -d '' f; do FILES+=("${f#./}"); done < <(find . -type f ! -path './.git/*' -print0)
fi
SCAN=()
for f in ${FILES[@]+"${FILES[@]}"}; do
  case "${f}" in
    .agents/skills/*|"${SELF}"|.public-hygiene-allow) continue ;;
  esac
  [[ -f "${f}" && ! -L "${f}" ]] && SCAN+=("${f}")
done

# allowed <file> <rule> <line-text> — true when an allowlist entry covers it.
allowed() {
  local file="$1" rule="$2" text="$3" path arule
  [[ -f "${ALLOW}" ]] || return 1
  printf '%s' "${text}" | grep -qiE 'fake|test|planted|example' || return 1
  while IFS='|' read -r path arule _; do
    path="$(printf '%s' "${path}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    arule="$(printf '%s' "${arule}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -z "${path}" || "${path}" == \#* ]] && continue
    # shellcheck disable=SC2053  # the allowlist path is a glob on purpose
    [[ "${file}" == ${path} && ( "${arule}" == "${rule}" || "${arule}" == "*" ) ]] && return 0
  done < "${ALLOW}"
  return 1
}

hits=0
allowed_hits=0
for entry in "${RULES[@]}"; do
  rule="${entry%%|*}"
  re="${entry#*|}"
  flags=(-nIE)
  if [[ "${re}" == i:* ]]; then flags=(-niIE); re="${re#i:}"; fi
  [[ ${#SCAN[@]} -gt 0 ]] || break
  while IFS= read -r match; do
    [[ -n "${match}" ]] || continue
    file="${match%%:*}"
    rest="${match#*:}"
    line="${rest%%:*}"
    text="${rest#*:}"
    if [[ "${rule}" == email ]]; then
      bad=0
      while IFS= read -r addr; do
        printf '%s' "${addr}" | grep -qiE "${ALLOWED_EMAILS}" || bad=1
      done < <(printf '%s' "${text}" | grep -oiE '[A-Za-z0-9._%+-]+@dailybot\.com')
      [[ "${bad}" -eq 1 ]] || continue
    fi
    if allowed "${file}" "${rule}" "${text}"; then
      allowed_hits=$((allowed_hits + 1))
      continue
    fi
    printf 'HIT %-14s %s:%s\n' "${rule}" "${file}" "${line}"
    hits=$((hits + 1))
  done < <(grep "${flags[@]}" -H -- "${re}" "${SCAN[@]}" 2>/dev/null)
done

if [[ "${hits}" -gt 0 ]]; then
  printf 'public hygiene: %d hit(s) in %d files scanned (%d allowlisted). Fix them, or — for a visibly fake test fixture only — list them in .public-hygiene-allow with a reason.\n' \
    "${hits}" "${#SCAN[@]}" "${allowed_hits}" >&2
  exit 1
fi
printf 'public hygiene: clean (%d files scanned, %d allowlisted fixture line(s))\n' "${#SCAN[@]}" "${allowed_hits}"
