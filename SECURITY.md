# Security Policy

## Supported versions

Security updates are applied on the active development line. Use the latest commit on `main`.

| Branch / tag | Supported |
| ------------ | --------- |
| `main`       | Yes       |
| Other tags   | Best effort; prefer upgrading to `main` |

Container images and Ansible runner images should be rebuilt from current `main` after security-related dependency updates.

## Reporting a vulnerability

**Do not** open a public GitHub issue for security vulnerabilities.

1. Use **[GitHub private vulnerability reporting](https://github.com/pamosima/netops-stack/security/advisories/new)** for this repository (**enabled**), **or**
2. Email **maintainers** at the address listed under [Security contacts](#security-contacts) with:
   - Short description and impact
   - Affected components (e.g. `netops-mcp-server`, GitLab Ansible image, ClickHouse exporter)
   - Steps to reproduce (proof-of-concept if safe to share)
   - Whether you’d like attribution

We treat reports as confidential until a fix is available.

## Response timelines (target)

| Severity | Examples | Initial response | Fix target |
| -------- | -------- | ---------------- | ---------- |
| **Critical** | RCE, auth bypass, credential theft | 48 hours | As fast as practical (often &lt; 7 days) |
| **High** | SQL/command injection, major data exposure | 5 business days | ~30 days |
| **Medium** | XSS, limited info disclosure, dependency CVEs with exploit path | 10 business days | Next reasonable release |
| **Low** | Hardening, defense-in-depth, non-exploitable findings | 15 business days | Backlog / bundled fixes |

Timelines depend on severity validation and maintainer availability. We will acknowledge receipt and keep you informed.

## Security best practices for users

- **Secrets:** Never commit tokens, passwords, or private keys. Use environment variables, GitLab CI/CD masked variables, or a secrets manager.
- **NetBox / GitLab / devices:** Restrict API tokens and SSH credentials; rotate on suspicion of compromise.
- **MCP server:** Run with least privilege; do not expose management interfaces to untrusted networks without TLS and access control.
- **Dependencies:** Apply Dependabot / renovate updates and rebuild container images regularly.
- **Supply chain:** Prefer pinned image digests and lockfiles (see repository Dockerfiles and `uv.lock` / compiled `requirements.txt`).

## Security contacts

| Role | Contact |
| ---- | ------- |
| **Preferred** | [GitHub Security Advisories](https://github.com/pamosima/netops-stack/security/advisories) (private reporting) |
| **Email** | `pamosima@cisco.com` |

Maintainers: update repository URLs in this file if you fork or change the canonical repo.

## Branch protection (repository administrators)

After enabling CodeQL and other checks, configure **`main`** protection:

1. **Settings → Branches → Branch protection rules → Add rule** (branch name pattern `main`).
2. Enable **Require a pull request before merging** (recommended: **1** approval).
3. Enable **Dismiss stale pull request approvals when new commits are pushed**.
4. Enable **Require status checks to pass** and require **`CodeQL`** (and any other required jobs).
5. Optionally: **Require branches to be up to date before merging**, **Do not allow bypassing**.

See also: [OpenSSF Scorecard](https://scorecard.dev/) and [GitHub branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
