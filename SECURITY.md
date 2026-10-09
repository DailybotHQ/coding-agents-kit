# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.1 (latest) | yes |
| 0.1.0 | no — affected by [GHSA-38vm-3jxc-qr92](https://github.com/DailybotHQ/coding-agents-kit/security/advisories/GHSA-38vm-3jxc-qr92); upgrade to 0.1.1 |

While the kit is `0.x`, only the latest release receives fixes.

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request for a
vulnerability.** Report it privately:

- GitHub: **Security → Report a vulnerability** on this repository
  (private vulnerability reporting), or
- email **security@dailybot.com** with "coding-agents-kit" in the subject.

Include the version (`ak --version`), your OS, what you did, what happened,
and what you expected. Do not include real API keys or tokens — describe
them by variable name.

## What to expect

| Step | Target |
| --- | --- |
| Acknowledgement | within 3 business days |
| Triage and severity assessment | within 7 days |
| Fix released — critical / high | within 30 days |
| Fix released — medium / low | in the next release |

We coordinate disclosure with you, publish a GitHub security advisory for
fixed issues, and credit reporters who want to be credited.

## Scope and threat model

Autonomy is the default: every launch adds the CLI's own autonomy flag, and
autonomy is meant for disposable or sandboxed environments; on a host, opt
out with `--ask` or `AGENTKIT_PERMISSIONS=ask`. What the kit protects
(provider keys, your files, accounts, shell rc files) and how, including the
documented exceptions, is described in [docs/SECURITY.md](docs/SECURITY.md). Vulnerabilities in the coding-agent
CLIs themselves belong to their vendors.
