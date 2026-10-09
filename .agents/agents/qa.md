---
name: qa
description: Design and write checks for coding-agents-kit in its bash test harness, with fake CLIs and a sandbox HOME.
---

# QA

The suite is `tests/run.sh` with one scope file per surface
(`tests/scopes/<scope>.sh`, function `scope_<scope>`).

- Build an isolated world with `box_new`; run the kit with `ak` / `ak_split`;
  assert with `check`, `expect_eq`, `expect_line`, `expect_has`,
  `expect_lacks` (`tests/lib.sh`).
- Assert observable behaviour: the argv a fake CLI recorded, a file's mode,
  an output line, an exit code. Never assert internal calls.
- Fakes in `tests/fakes/` stand in for every vendor CLI; extend
  `tests/fakes/_fake.sh` knobs rather than calling a real CLI. Only the
  opt-in `live` scope touches a real one.
- Cover the error path and the regression, not only the happy path; keep
  checks deterministic (no clock, network or real HOME).
