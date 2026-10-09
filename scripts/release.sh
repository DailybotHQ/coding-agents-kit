#!/usr/bin/env bash
# Release helper, used by .github/workflows/release.yml and runnable locally
# from a checkout (it only reads the repository and writes into OUTDIR).
#
#   scripts/release.sh check <tag>            the tag is annotated, matches lib/common.py VERSION,
#                                             and CHANGELOG.md has its section
#   scripts/release.sh notes <version>        prints that CHANGELOG.md section (release notes)
#   scripts/release.sh build <tag> <outdir>   source tarball + SHA256SUMS (+ NOTES.md) in <outdir>
#
# SHA256SUMS lists every shipped file (verify from a checkout of the tag)
# and the tarball (verify from the download directory).
set -euo pipefail

SHIPPED="bin lib providers.toml skills docs win install.sh install.ps1 README.md LICENSE CREDITS.md CHANGELOG.md"

die() { printf 'release: %s\n' "$*" >&2; exit 1; }

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}

kit_version() {
  python3 -c 'import re,sys; print(re.search(r"^VERSION = \"([^\"]+)\"", open(sys.argv[1]).read(), re.M).group(1))' lib/common.py
}

notes() {
  local version="$1"
  awk -v v="${version}" '
    $0 ~ "^## \\[" v "\\]" { on = 1; next }
    on && /^## \[/ { exit }
    on && /^\[[^]]+\]: / { exit }
    on { print }
  ' CHANGELOG.md | sed -e '/./,$!d' | awk 'NF { blank = 0; print; next } { if (!blank) print; blank = 1 }'
}

check() {
  local tag="$1" version
  [[ "${tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "${tag} is not a vX.Y.Z[-pre] tag"
  [[ "$(git cat-file -t "${tag}" 2>/dev/null)" == tag ]] || die "${tag} is not an annotated tag (git tag -a)"
  version="$(git show "${tag}:lib/common.py" | python3 -c 'import re,sys; print(re.search(r"^VERSION = \"([^\"]+)\"", sys.stdin.read(), re.M).group(1))')"
  [[ "v${version}" == "${tag}" ]] || die "${tag} does not match VERSION ${version} in lib/common.py at that tag"
  [[ -n "$(git show "${tag}:CHANGELOG.md" | grep -E "^## \[${version//./\\.}\]")" ]] || die "CHANGELOG.md has no [${version}] section at ${tag}"
  printf 'release: %s is annotated, matches VERSION and has a changelog section\n' "${tag}"
}

build() {
  local tag="$1" out="$2" name version prerelease
  name="coding-agents-kit-${tag}"
  version="${tag#v}"
  mkdir -p "${out}"
  out="$(cd "${out}" && pwd)"
  git archive --format=tar.gz --prefix="${name}/" -o "${out}/${name}.tar.gz" "${tag}"
  # Checksums of the files *at the tag* (from the tarball), never the working tree.
  local tmp f
  tmp="$(mktemp -d)"
  tar -xzf "${out}/${name}.tar.gz" -C "${tmp}"
  : > "${out}/SHA256SUMS"
  # shellcheck disable=SC2086  # SHIPPED is a fixed word list
  while IFS= read -r f; do
    ( cd "${tmp}/${name}" && sha256 "${f}" ) >> "${out}/SHA256SUMS"
  done < <(git ls-tree -r --name-only "${tag}" -- ${SHIPPED})
  ( cd "${out}" && sha256 "${name}.tar.gz" ) >> "${out}/SHA256SUMS"
  rm -rf "${tmp:?}"
  prerelease=""
  [[ "${version}" == *-* ]] && prerelease=" (pre-release)"
  {
    printf 'coding-agents-kit %s%s — interface %s.\n\n' "${tag}" "${prerelease}" \
      "$(python3 -c 'import re,sys; print(re.search(r"^INTERFACE = (\d+)", open(sys.argv[1]).read(), re.M).group(1))' lib/common.py)"
    printf '```bash\ngit clone --branch %s https://github.com/DailybotHQ/coding-agents-kit && ./coding-agents-kit/install.sh\n```\n\n' "${tag}"
    notes "${version%%-*}" 2>/dev/null | grep -q . && notes "${version%%-*}" || notes "${version}"
    printf '\n### Verify\n\n`SHA256SUMS` lists every shipped file (verify from a checkout of the tag: `shasum -a 256 -c SHA256SUMS`) and the source tarball (verify it from the directory you downloaded it to).\n'
  } > "${out}/NOTES.md"
  printf 'release: built %s/%s.tar.gz, SHA256SUMS (%s entries), NOTES.md\n' "${out}" "${name}" "$(wc -l < "${out}/SHA256SUMS" | tr -d ' ')"
}

cd "$(git rev-parse --show-toplevel)"
case "${1:-}" in
  check) check "${2:?tag}" ;;
  notes) notes "${2:?version}" ;;
  build) build "${2:?tag}" "${3:?outdir}" ;;
  version) kit_version ;;
  *) die "usage: scripts/release.sh check <tag> | notes <version> | build <tag> <outdir> | version" ;;
esac
