# shellcheck shell=bash
# Static checks: syntax, shellcheck, python compatibility, leak markers.

lint_shell_files() {
  local f
  for f in "${ROOT}"/bin/* "${ROOT}"/lib/*.sh "${ROOT}/install.sh" "${ROOT}/tests/run.sh" \
      "${ROOT}/tests/lib.sh" "${ROOT}"/tests/scopes/*.sh "${ROOT}"/win/*.sh; do
    [[ -f "${f}" ]] && printf '%s\n' "${f}"
  done
  return 0
}

lint_product_paths() {
  local p
  for p in bin lib providers.toml skills win install.sh install.ps1 docs README.md CHANGELOG.md AGENTS.md; do
    [[ -e "${ROOT}/${p}" ]] && printf '%s\n' "${ROOT}/${p}"
  done
  return 0
}

scope_lint() {
  local f py39 hits
  local -a shells=() products=()
  while IFS= read -r f; do shells+=("${f}"); done < <(lint_shell_files)
  while IFS= read -r f; do products+=("${f}"); done < <(lint_product_paths)

  for f in "${shells[@]}"; do
    check "bash -n ${f#"${ROOT}/"}" bash -n "${f}"
  done
  for f in "${FAKES}"/*; do
    check "sh -n tests/fakes/${f##*/}" sh -n "${f}"
  done

  if compgen -G "${ROOT}/lib/*.py" >/dev/null; then
    check "python3 compiles lib/*.py" "${AK_PY}" -c '
import sys
for f in sys.argv[1:]:
    with open(f) as h:
        compile(h.read(), f, "exec")' "${ROOT}"/lib/*.py "${ROOT}"/tests/py/*.py
    # The kit promises python3 >= 3.9: compile with a 3.9 when one exists,
    # so 3.10+ syntax (match, X | Y unions) cannot slip in.
    py39=""
    for f in /usr/bin/python3 python3.9; do
      if command -v "${f}" >/dev/null 2>&1 && "${f}" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 9))' 2>/dev/null; then
        py39="$(command -v "${f}")"; break
      fi
    done
    if [[ -n "${py39}" ]]; then
      check "python 3.9 compiles lib/*.py" "${py39}" -c '
import sys
for f in sys.argv[1:]:
    with open(f) as h:
        compile(h.read(), f, "exec")' "${ROOT}"/lib/*.py "${ROOT}"/tests/py/*.py
    else
      skip "python 3.9 compile (no python3.9 on this machine; CI covers it)"
    fi
  fi

  if command -v shellcheck >/dev/null 2>&1; then
    check "shellcheck -S warning (bin lib install tests)" shellcheck -S warning -x "${shells[@]}"
    check "shellcheck -s sh tests/fakes" shellcheck -S warning -s sh "${FAKES}"/*
    check "the release gate's exact form: shellcheck -S warning bin/* lib/*.sh install.sh tests/run.sh" \
      bash -c "cd '${ROOT}' && shellcheck -S warning bin/* lib/*.sh install.sh tests/run.sh"
  else
    skip "shellcheck (not installed: brew install shellcheck / apt-get install shellcheck)"
  fi

  # No key-shaped string may ever be committed, in any product or test file.
  hits="$(grep -rIlE '(sk-[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,})' \
      ${products[@]+"${products[@]}"} "${ROOT}/tests" 2>/dev/null || true)"
  if [[ -z "${hits}" ]]; then pass "no secret-looking strings in the kit"; else fail "secret-looking strings in: ${hits}"; fi

  # A public kit: no private org, private repository or personal path.
  hits="$(grep -rIlE "${AGENTKIT_PRIVATE_MARKERS:-DailyBot-Inc|coding-agent-host-kit|dailybot-core|/Users/[a-z]|/home/[a-z]+/projects}" \
      --exclude=lint.sh ${products[@]+"${products[@]}"} "${ROOT}/tests" 2>/dev/null || true)"
  if [[ -z "${hits}" ]]; then pass "no private or personal references in the kit"; else fail "private references in: ${hits}"; fi

  # One version everywhere it is stated.
  local version
  version="$("${AK_PY}" -c 'import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import common; print(common.VERSION)' "${ROOT}")"
  check "the skill's version equals the kit's (${version})" grep -q "^version: \"${version}\"$" "${ROOT}/skills/agentkit/SKILL.md"
  check "the README installs tag v${version}" grep -q -- "--branch v${version} " "${ROOT}/README.md"
  check "the doctor schema pins tag v${version}" grep -q "/blob/v${version}/" "${ROOT}/docs/schema/doctor-v1.json"
  if [[ -f "${ROOT}/CHANGELOG.md" ]]; then
    check "CHANGELOG.md has a ${version} section" grep -q "^## \[${version}\]" "${ROOT}/CHANGELOG.md"
  fi

  # Every relative link in the README and docs/ resolves.
  hits="$(cd "${ROOT}" && for f in README.md docs/*.md; do
      grep -oE '\]\([^)#]+' "${f}" | sed 's/^](//' | grep -vE '^(https?:|mailto:)' | while read -r link; do
        [[ -e "$(dirname "${f}")/${link}" ]] || printf '%s -> %s; ' "${f}" "${link}"
      done
    done)"
  if [[ -z "${hits}" ]]; then pass "every relative link in README.md and docs/ resolves"; else fail "broken links: ${hits}"; fi

  # bin/ holds only executables the installer puts on PATH.
  hits=""
  for f in "${ROOT}"/bin/*; do
    [[ -e "${f}" ]] || continue
    [[ -x "${f}" && "${f}" != *.md ]] || hits="${hits} ${f##*/}"
  done
  if [[ -z "${hits}" ]]; then pass "bin/ holds only executables"; else fail "non-executables in bin/:${hits}"; fi
}
