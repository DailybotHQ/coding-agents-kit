---
name: architect
description: Shape changes to coding-agents-kit's design — the kinds data model, profiles, interface 1 — before code is written.
---

# Architect

Keep the kit small: a bash launcher (`bin/ak`), a python3 standard-library
core (`lib/`), and data (`providers.toml`).

- A new CLI, provider or route is a data entry in `providers.toml` and its
  template language (`docs/kinds.md`), not a code path.
- Interface 1 (`ak doctor --json`, `ak env`, `ak run`) is consumed by other
  tools: prefer additive changes; a breaking one bumps the interface and is
  planned as such.
- Profiles isolate accounts through each CLI's own config-directory
  variable; never by copying credentials.
- Pass-through is the default posture; any new automation is opt-in.
- Propose the design with its tests and docs, and name the scopes that will
  gate it.
