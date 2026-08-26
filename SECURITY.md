# Security Policy

## Supported versions

Until Keepygaga reaches 1.0, security fixes are provided only for an unmodified
checkout at the latest commit on the upstream `main` branch.

| Source revision | Supported |
| --- | --- |
| Latest unmodified upstream `main` checkout | Yes |
| Older commits, tags, forks, or locally modified checkouts | No |

## Reporting a vulnerability

Use GitHub's [private vulnerability reporting
form](https://github.com/TimWongUp/keepygaga/security/advisories/new). Do not
open a public issue for a suspected vulnerability.

Please include:

- the exact affected commit SHA, plus the version if known;
- the impact and conditions required to reproduce the issue;
- minimal, sanitized reproduction steps;
- any suggested mitigation, if known.

Do not include real memory pages, credentials, tokens, or other personal data.
The maintainer will acknowledge reports as soon as practical and coordinate
validation, remediation, and disclosure through the private advisory.

Issues involving unauthorized memory access or mutation, path traversal,
unsafe file replacement, secret exposure, or bypass of explicit delete
authorization are especially important to report privately.
