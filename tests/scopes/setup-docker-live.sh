# shellcheck shell=bash
# Opt-in: build the rendered Dockerfile with a real Docker and run `ak doctor`
# in the image. It needs Docker and the network (it downloads the release
# tarball of the pinned tag), so it is never part of the default run:
#     AGENTKIT_TEST_LIVE=1 bash tests/run.sh setup-docker-live

scope_setup_docker_live() {
  local tag="v0.3.0" digest="8c163a81fa31151cd577797f07cfbe3e61dad49ff691de0b6d5de0975f1cc8ca" dir out status
  if [[ "${AGENTKIT_TEST_LIVE:-}" != "1" ]]; then
    skip "setup-docker-live: set AGENTKIT_TEST_LIVE=1 to build the recipe with a real Docker"
    return 0
  fi
  if ! PATH="${REAL_PATH}" command -v docker >/dev/null 2>&1; then
    skip "setup-docker-live: docker is not installed here"
    return 0
  fi
  dir="${SANDBOX}/docker-live"
  mkdir -p "${dir}"
  PATH="${REAL_PATH}" "${AK_PY}" "${ROOT}/lib/ak.py" setup docker --ref "${tag}" --sha256 "${digest}" --out "${dir}/Dockerfile"
  if PATH="${REAL_PATH}" docker build -q -t agentkit-setup-live "${dir}" >/dev/null 2>&1; then
    pass "setup-docker-live: the rendered Dockerfile builds (the digest was verified before unpacking)"
    out="$(PATH="${REAL_PATH}" docker run --rm agentkit-setup-live ak doctor --json 2>&1)"; status=$?
    expect_eq "setup-docker-live: ak doctor runs in the image as a non-root user" "${status}" 0
    expect_has "setup-docker-live: ... and reports interface 1" "${out}" '"interface": 1'
    PATH="${REAL_PATH}" docker rmi -f agentkit-setup-live >/dev/null 2>&1
  else
    fail "setup-docker-live: the rendered Dockerfile did not build"
  fi
}
