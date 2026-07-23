# Security Policy

## Supported versions

Curator is pre-1.0. Security fixes target the latest released `0.1.x` and the `dev` branch.

| Version | Supported |
|---|---|
| latest `0.1.x` | ✅ |
| older | ❌ |

## Reporting a vulnerability

**Please do not report security issues in public GitHub issues.**

Use GitHub's private reporting instead: open the repository's **Security → Report a
vulnerability** ([Security Advisories](https://github.com/JasonZQH/CURATOR/security/advisories/new)).
This keeps the report private until a fix is available.

Please include:

- what you found and where (file / command / component),
- steps to reproduce or a proof of concept,
- the impact you expect.

You can expect an initial acknowledgement within a few days. Once a fix is ready we'll
coordinate a release and credit you if you'd like.

## Scope note

Curator dispatches real provider CLIs (Claude Code, Codex) with workspace-write permission and
records state under `.curator/`. Reports about the trust boundary — permission gating,
attribution/evidence integrity, or the clean-tree guard — are in scope and especially welcome.
