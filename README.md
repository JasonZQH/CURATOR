# Curator

[![CI](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml/badge.svg)](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

**A local-first coding-agent workbench that orchestrates real provider CLIs behind an
auditable, scheduler-owned control plane.**

Curator records accepted user goals, compiles them into auditable workflow sessions,
dispatches real provider CLIs such as **Claude Code** or **Codex**, runs deterministic
verification, captures evidence, and pauses for a human decision when provider setup,
verification, scope, permissions, or workspace state need one.

The scheduler — not the provider — owns retry, pause, stop, and resume decisions, so
failures, permission problems, missing verification commands, and scope changes stay
inspectable instead of hidden inside a chat transcript.

> Curator has no synthetic provider fallback. The CLI, REPL, scheduler, provider setup,
> and diagnostics require real configured providers for user work (the test suite uses
> local fake providers only).

## Install

Curator is a Python CLI. Any of the following work:

```bash
# One-line installer (bootstraps uv, then installs Curator)
curl -fsSL https://raw.githubusercontent.com/JasonZQH/CURATOR/main/install.sh | sh

# With pipx
pipx install "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0"

# With uv (no global install; run on demand)
uvx --from "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0" curator
```

Pin to a released tag (`@v0.1.0`) for reproducible installs, or omit it to track `main`.

### From source

```bash
git clone https://github.com/JasonZQH/CURATOR.git
cd CURATOR
uv sync                 # or: python -m venv .venv && .venv/bin/pip install -e .
uv run curator          # or: source .venv/bin/activate && curator
```

## Quickstart

```bash
curator init --yes            # create local .curator/ state
curator provider add claude-code
curator provider add codex
curator provider list
curator                       # open the natural-language shell
```

Inside the shell, connect and bind providers to functional slots:

```
/provider add claude-code
/agent bind writer.default claude-code
/agent bind reviewer.default codex
```

Then type what you want to work on. Small requests start immediately; use `/gate on`
to review the goal proposal first. Useful commands: `/workbench`, `/node current`,
`/memory`, `/resume <answer>`, `/revise <scope>`, `/help`.

## How it works

1. User text becomes a durable goal draft and an accepted goal revision.
2. The app creates a single-writer workflow session.
3. The **writer** provider receives a context package rendered into the CLI prompt.
4. Curator blocks a dirty git workspace before writer dispatch to avoid misattribution.
5. The **verifier** runs discovered or explicit verification commands and produces hashed evidence.
6. A fresh-context **reviewer** provider reviews the implementation and verification evidence.
7. A **human confirmation gate** pauses before marking delivery done.

Every iteration, decision (with reason), provider run, evidence ref, pause, and resume is
persisted to a local SQLite ledger under `.curator/`, so a run is fully replayable and
`/resume` can continue a paused loop from durable state.

## Why

Providers stay out of scheduler control flow: they produce typed output, provider
responses, workspace evidence, and streamed events, while the scheduler owns retry,
pause, stop, and resume. Real provider setup is explicit on purpose — a fallback provider
creates misleading confidence, so a missing or broken CLI blocks setup and a goal run
without a configured provider pauses with next-step guidance instead of synthesizing
success.

## Development

```bash
uv sync --dev
source .venv/bin/activate
pytest -p no:cacheprovider -q
ruff check src tests
```

Contributions branch off `origin/dev` and merge back via pull request; `main` is the
protected, release-tagged branch and is never committed to directly. See
[docs/orchestration.html](docs/orchestration.html) for the runtime and control-plane
design, plus the other design notes under [`docs/`](docs/).

## License

[MIT](LICENSE)

## Roadmap

- Development-only simulator outside production CLI paths for demos.
- Parse structured provider-reported verification commands from final output.
- Opt-in dirty-workspace mode with stronger diff partitioning.
- Provider health and quota tracking for smarter slot routing.
- Richer reviewer evidence while preserving fresh-context isolation.
