<!--
Thanks for contributing to Curator! A few ground rules:
- Base this PR on `dev` (not `main`). main is admin-only / release-tagged.
- Only invited contributors can merge; a code-owner review + green CI are required.
-->

## Summary

<!-- What does this change and why? Link the issue it addresses. -->

Closes #

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Docs
- [ ] Chore / infra

## Checklist

- [ ] Base branch is **`dev`**.
- [ ] `pytest -p no:cacheprovider -q` passes locally.
- [ ] `ruff check src tests` is clean.
- [ ] No `.curator/` state or `*.sqlite` ledgers are committed.
- [ ] Shipping code adds no synthetic/mock provider (no fallback theater).
- [ ] Docs/README/CHANGELOG updated if user-facing behavior changed.
