# Contributing to Curator

Thanks for your interest in Curator. This project uses a **gated open-source model**: the
code is MIT-licensed and readable by everyone, but the canonical repository is protected so
that every change to it is reviewed and attributed.

## Who can do what

| You are… | You can… |
|---|---|
| **Anyone** | Read the code, fork it, and **[open an issue](https://github.com/JasonZQH/CURATOR/issues/new/choose)** (bug report or feature request). You cannot push to this repository. |
| **Invited contributor** (collaborator with write access) | Push feature/fix branches to the repo and open **pull requests into `dev`**. |
| **Admin / maintainer** | Review and merge PRs into `dev`, and merge `dev` → `main` as a version bump. |

Want to become a contributor? Open an issue or comment on one you'd like to take, and the
maintainer can invite you.

## Branching model

- **`dev`** — the integration branch. All work lands here first, via pull request.
- **`main`** — protected and release-tagged. Only an admin merges `dev` → `main`, and only as
  a version bump. Never commit to `main` directly.
- Feature/fix branches: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`,
  `chore/<short-name>`, branched from `dev`.

Direct pushes to `dev` and `main` are rejected by branch protection — everything goes through
a reviewed PR.

## Local development

Curator uses [`uv`](https://docs.astral.sh/uv/). Python 3.11+.

```bash
git clone https://github.com/JasonZQH/CURATOR.git
cd CURATOR
uv sync --dev
```

Run the tool from source without installing globally:

```bash
uv run curator            # or: source .venv/bin/activate && curator
```

## Before you open a PR

Keep the suite green and the tree clean:

```bash
source .venv/bin/activate
pytest -p no:cacheprovider -q
ruff check src tests
```

- **Base your PR on `dev`**, not `main`.
- Never commit `.curator/` state or `*.sqlite` ledgers (CI's `guard` job blocks them).
- Shipping code must not define a synthetic/mock provider (no fallback theater — also CI-guarded).
- Link the issue your PR addresses.

```bash
git checkout -b feat/your-change origin/dev
# ...work, commit...
git push -u origin feat/your-change     # then open a PR into dev
```

CI (`.github/workflows/ci.yml`) runs the guard checks, pytest + ruff on Python 3.11 and 3.12,
and a macOS smoke test on every PR. All checks must pass and a code-owner must approve before
a PR can merge.

## Releases (maintainers)

1. Merge the release PRs into `dev`; confirm CI is green.
2. Open a `dev` → `main` PR and merge it (admin only).
3. Tag on `main`: `git tag v0.1.0 && git push origin v0.1.0` — the `release-smoke` CI job
   builds and clean-installs the wheel and sdist.

## Reporting security issues

Please do **not** open a public issue for vulnerabilities. See [SECURITY.md](SECURITY.md).
