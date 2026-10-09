## Summary

<!-- What changes and why, in a few lines. -->

## Linked issue

<!-- Closes #… (or "none") -->

## Test evidence

<!-- The scopes you ran and their final line, e.g. `bash tests/run.sh dispatch profiles` → passed: N  failed: 0 -->

## Checklist

- [ ] `bash tests/run.sh` (or the scopes for the touched surface) passes
- [ ] `bash scripts/check-public-hygiene.sh` passes
- [ ] No secrets and no private context (personal paths, internal names, non-public addresses) in code, docs, tests or commit messages
- [ ] Docs updated for the touched surface (`docs/`, README, skill)
- [ ] Interface 1 (`ak doctor --json`, `ak env`, `ak run`) unchanged — or the breaking change is called out
- [ ] Conventional Commit title
