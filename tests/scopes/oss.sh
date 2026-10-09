# shellcheck shell=bash
# The public repository standard (ecosystem amendment A3): the S1 file set,
# its required content and order, and (S4) the release workflow.

scope_oss() {
  local f out
  for f in README.md LICENSE CHANGELOG.md CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md AGENTS.md CREDITS.md \
      docs/TESTING_GUIDE.md .gitignore .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml \
      .github/ISSUE_TEMPLATE/config.yml .github/PULL_REQUEST_TEMPLATE.md .github/CODEOWNERS .github/dependabot.yml \
      .github/workflows/ci.yml .public-hygiene-allow scripts/check-public-hygiene.sh; do
    check "S1 ${f} exists" test -s "${ROOT}/${f}"
  done

  # README: the standard sections, in order, and the footer.
  out="$(grep -E '^## ' "${ROOT}/README.md" | tr '\n' '|')"
  expect_eq "README sections in the standard order" "${out}" \
    "## What it is|## Install|## Quickstart|## Documentation|## Security|## Contributing|## License|"
  check "README opens with the title and a one-line value" bash -c "head -3 '${ROOT}/README.md' | grep -q '^# coding-agents-kit\$' && sed -n 3p '${ROOT}/README.md' | grep -q '\`ak'"
  for b in 'actions/workflows/ci.yml/badge.svg' 'img.shields.io/github/v/release' 'img.shields.io/github/license'; do
    check "README badge: ${b}" grep -q "${b}" "${ROOT}/README.md"
  done
  check "README installs a pinned tag" grep -qE -- '--branch v[0-9]+\.[0-9]+\.[0-9]+ ' "${ROOT}/README.md"
  check "README links SECURITY.md and CONTRIBUTING.md" bash -c "grep -q '](SECURITY.md)' '${ROOT}/README.md' && grep -q '](CONTRIBUTING.md)' '${ROOT}/README.md'"
  expect_eq "README ends with the ecosystem footer" "$(tail -1 "${ROOT}/README.md")" \
    "Part of the [DeepWorkPlan](https://deepworkplan.com) ecosystem — works on its own."

  # LICENSE, CHANGELOG, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT.
  check "LICENSE is MIT for DailybotHQ contributors" bash -c "head -1 '${ROOT}/LICENSE' | grep -q 'MIT License' && grep -q 'Copyright (c) 2026 DailybotHQ contributors' '${ROOT}/LICENSE'"
  check "CHANGELOG follows Keep a Changelog" grep -q 'keepachangelog.com/en/1.1.0' "${ROOT}/CHANGELOG.md"
  check "CHANGELOG has an Unreleased section and dated versions" bash -c "grep -q '^## \[Unreleased\]' '${ROOT}/CHANGELOG.md' && grep -qE '^## \[[0-9]+\.[0-9]+\.[0-9]+\] - [0-9]{4}-[0-9]{2}-[0-9]{2}\$' '${ROOT}/CHANGELOG.md'"
  check "CHANGELOG has a Security subsection where it applies" grep -q '^### Security' "${ROOT}/CHANGELOG.md"
  for w in 'tests/run.sh' 'Conventional Commits' 'pull request' 'No DCO' 'AGENTS.md' 'check-public-hygiene'; do
    check "CONTRIBUTING covers: ${w}" grep -q "${w}" "${ROOT}/CONTRIBUTING.md"
  done
  for w in '## Supported versions' 'security@dailybot.com' 'Report a vulnerability' 'Do not open a public issue' 'Acknowledgement'; do
    check "SECURITY.md covers: ${w}" grep -q "${w}" "${ROOT}/SECURITY.md"
  done
  check "CODE_OF_CONDUCT is the Contributor Covenant 2.1 with a contact" bash -c "grep -q 'version 2.1' '${ROOT}/CODE_OF_CONDUCT.md' && grep -qE '(conduct|security)@dailybot.com' '${ROOT}/CODE_OF_CONDUCT.md'"

  # Agent entry point and ignore rules.
  expect_eq "CLAUDE.md is a symlink to AGENTS.md" "$(readlink "${ROOT}/CLAUDE.md")" "AGENTS.md"
  for w in '.dwp/' 'tmp/' '.env' '.env.*' '!.env.example' '.DS_Store'; do
    check ".gitignore has ${w}" grep -qxF -- "${w}" "${ROOT}/.gitignore"
  done

  # .github.
  check "issue config disables blank issues and routes security privately" bash -c "grep -q 'blank_issues_enabled: false' '${ROOT}/.github/ISSUE_TEMPLATE/config.yml' && grep -q 'security/advisories/new' '${ROOT}/.github/ISSUE_TEMPLATE/config.yml'"
  check "the PR template asks for evidence and no secrets / private context" bash -c "grep -q 'Test evidence' '${ROOT}/.github/PULL_REQUEST_TEMPLATE.md' && grep -q 'No secrets and no private context' '${ROOT}/.github/PULL_REQUEST_TEMPLATE.md'"
  check "CODEOWNERS names the maintainer for everything" grep -qE '^\* @[A-Za-z0-9-]+' "${ROOT}/.github/CODEOWNERS"
  check "Dependabot watches github-actions weekly" bash -c "grep -q 'package-ecosystem: github-actions' '${ROOT}/.github/dependabot.yml' && grep -q 'interval: weekly' '${ROOT}/.github/dependabot.yml'"
  check "CI runs on pull requests and pushes to main" bash -c "grep -q 'pull_request:' '${ROOT}/.github/workflows/ci.yml' && grep -q 'branches: \[main\]' '${ROOT}/.github/workflows/ci.yml'"
  check "CI runs the full suite and the public-hygiene check" bash -c "grep -q 'bash tests/run.sh' '${ROOT}/.github/workflows/ci.yml' && grep -q 'scripts/check-public-hygiene.sh' '${ROOT}/.github/workflows/ci.yml'"
  if grep -hE '^\s*-?\s*uses:' "${ROOT}"/.github/workflows/*.yml | grep -vqE '@[0-9a-f]{40}( |$)'; then
    fail "every GitHub Action is pinned by commit SHA"
  else pass "every GitHub Action is pinned by commit SHA"; fi
  for f in "${ROOT}"/.github/ISSUE_TEMPLATE/*.yml "${ROOT}"/.github/dependabot.yml "${ROOT}"/.github/workflows/*.yml; do
    check "valid YAML shape (no tabs): ${f#"${ROOT}/"}" bash -c "! grep -q \$'\t' '${f}'"
  done

  # S4: the release workflow and its helper.
  check "release workflow triggers on vX.Y.Z tags" grep -q "tags: \['v\*\.\*\.\*'\]" "${ROOT}/.github/workflows/release.yml"
  check "release workflow checks the tag, tests, and publishes SHA256SUMS" bash -c "grep -q 'release.sh check' '${ROOT}/.github/workflows/release.yml' && grep -q 'tests/run.sh' '${ROOT}/.github/workflows/release.yml' && grep -q SHA256SUMS '${ROOT}/.github/workflows/release.yml' && grep -q -- '--prerelease' '${ROOT}/.github/workflows/release.yml'"
  out="$(cd "${ROOT}" && bash scripts/release.sh notes "$(bash scripts/release.sh version)")"
  expect_has "release notes come from the CHANGELOG section of the current version" "${out}" "###"
  # release.sh check, in a throwaway repository (CI checkouts carry no tags).
  local rel="${SANDBOX}/release-repo" version
  version="$(cd "${ROOT}" && bash scripts/release.sh version)"
  mkdir -p "${rel}/lib"
  cp "${ROOT}/lib/common.py" "${rel}/lib/"; cp "${ROOT}/CHANGELOG.md" "${rel}/"
  ( cd "${rel}" && git init -q && git add -A \
      && git -c user.name=t -c user.email=t@example.invalid commit -qm init \
      && git -c user.name=t -c user.email=t@example.invalid tag -a "v${version}" -m release \
      && git tag v9.9.9 && git -c user.name=t -c user.email=t@example.invalid tag -a v9.9.8 -m wrong )
  check "release.sh check accepts an annotated tag matching VERSION" bash -c "cd '${rel}' && bash '${ROOT}/scripts/release.sh' check v${version}"
  check "release.sh check refuses a lightweight tag" bash -c "cd '${rel}' && ! bash '${ROOT}/scripts/release.sh' check v9.9.9"
  check "release.sh check refuses a tag that does not match VERSION" bash -c "cd '${rel}' && ! bash '${ROOT}/scripts/release.sh' check v9.9.8"
}
