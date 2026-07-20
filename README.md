<div align="center">

<img src="docs/assets/carutor-logo.png" alt="Curator" width="560">

**The coding-agent workbench where the scheduler — not the model — stays in control.**

Curator orchestrates real provider CLIs like **Claude Code** and **Codex** through an
auditable control plane: it plans an accepted goal, dispatches a single writer, gates the
loop on **deterministic verification**, runs a **fresh-context reviewer**, and pauses for
you at a human confirmation gate — recording every decision, evidence ref, and pause to a
local, replayable ledger.

[![CI](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml/badge.svg)](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Built by JasonZQH](https://img.shields.io/badge/built%20by-JasonZQH-orange.svg)](https://github.com/JasonZQH)

</div>

---

Most agent tools hand the model the keys and hope. Curator keeps the model doing what it
is good at — writing code — while a deterministic scheduler owns retry, pause, stop, and
resume. When a run fails, stalls, needs a permission, or drifts in scope, you see exactly
why, and you can resume it later from durable state instead of starting over.

| | |
|---|---|
| **Real providers, not a wrapper** | Dispatches the Claude Code and Codex CLIs behind an async streaming driver — tool calls, permissions, and output flow through as typed events, not an opaque chat. |
| **The scheduler owns control flow** | Providers produce typed output; Curator alone decides continue, retry, pause, stop, and resume. Control flow never hides inside a transcript. |
| **Deterministic verification** | The loop exits on real test/command results with content-hashed evidence — not on a model's self-reported "looks good." |
| **Fresh-context review** | A second provider reviews the implementation and verification evidence without the writer's context, catching what the author cannot see. |
| **Everything is on the ledger** | Every iteration, decision-with-reason, provider run, evidence ref, pause, and resume is a durable SQLite row under `.curator/`. Runs are auditable and replayable. |
| **Resume from anywhere** | Paused a loop yesterday? `/resume` rebuilds execution state from the ledger and continues — a confirm-gate "yes" finishes it, anything else re-runs the writer with your guidance. |
| **A memory that learns** | Retries, failures, and pauses are distilled into memory entries and injected into future context packages, so the agent carries lessons forward. Inspect them with `/memory`. |
| **Local-first, no fallback theater** | No synthetic provider. A missing or broken CLI blocks setup and an unconfigured run pauses with next steps — never fake success. |

## Quick install

Curator is a Python CLI. Pick whichever fits your setup:

```bash
# One line — bootstraps uv, then installs the curator CLI (macOS / Linux / WSL2)
curl -fsSL https://raw.githubusercontent.com/JasonZQH/CURATOR/main/install.sh | sh
```

```bash
# With pipx
pipx install "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0"

# With uv (run on demand, no global install)
uvx --from "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0" curator
```

> **Heads up:** pin a released tag (`@v0.1.0`) for reproducible installs, or drop it to
> track `main`. On Windows, run inside WSL2.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/JasonZQH/CURATOR.git
cd CURATOR
uv sync
uv run curator          # or: source .venv/bin/activate && curator
```

</details>

## Getting started

```bash
curator init --yes                 # create local .curator/ state
curator provider add claude-code   # detect and register a provider
curator provider add codex
curator                            # open the natural-language shell
```

Inside the shell, connect providers and bind them to functional slots, then just say what
you want to work on:

```
/provider add claude-code
/agent bind writer.default claude-code
/agent bind reviewer.default codex
> add a --json flag to the export command
```

Small requests start immediately; `/gate on` reviews the goal proposal first.

> **Heads up:** Curator dispatches a real CLI with workspace-write permission. It blocks a
> dirty git tree before a writer runs so changes are never misattributed — commit or stash
> first.

## How a run works

1. Your text becomes a durable goal draft, then an accepted goal revision.
2. Curator compiles a single-writer Phase 0 workflow session.
3. The **writer** provider gets a context package through stdin (prompt text is excluded from argv).
4. The **verifier** runs discovered or explicit commands and produces hashed evidence.
5. A fresh-context **reviewer** provider assesses the implementation and verification.
6. A **human confirmation gate** pauses before delivery is marked done.
7. Every step lands on the ledger, so `/resume` can continue a paused loop later.

The Excalidraw blueprint is the V1 target rather than the current v0-alpha contract. It
adds durable Project/Session/Goal/Task entities, dependency-aware scheduling, separate
Agent/AgentRuntime/ExecutionRuntime identities, capability approvals, artifact and memory
manifests, worker leases and heartbeats, provider-native TUI handoff, and bounded parallel
workers. Until those pieces are implemented and tested, this README intentionally describes
the sequential Phase 0 behavior above.

## Command reference

| Area | Commands |
|---|---|
| Start work | type a request · `/gate on\|off` · `yes` / `no` / `edit <text>` |
| Watch progress | `/workbench` · `/node current` · `/evidence` |
| Handle pauses | `/resume <answer>` · `/resume --run <id> <answer>` · `/revise <scope>` · `/cancel` |
| Providers | `/provider add` · `/providers` · `/agent bind <slot> <profile>` |
| Learn & inspect | `/memory` · `/history` · `/sessions` · `/status` · `/help` |
| Terminal | `curator init` · `curator provider add\|list` · `curator reset` · `curator doctor` · `curator status` |

Full-screen TUI also provides Up/Down history, Tab completion, Shift+Enter/Ctrl+J
continuation lines, animated busy timing, Esc interruption, and two-stage Ctrl+C shutdown.

## Documentation

| Doc | What it covers |
|---|---|
| [orchestration.html](docs/orchestration.html) | Runtime flow, the control-plane boundary, and the decision layer |
| [provider-profile-layer.html](docs/provider-profile-layer.html) | Provider profiles, slots, and bindings |
| [runtime-workspace-ui.html](docs/runtime-workspace-ui.html) | The inspectable runtime workspace |
| [future-optimizations.html](docs/future-optimizations.html) | Roadmap and design trade-offs |
| [shell-adapter-boundary.html](docs/shell-adapter-boundary.html) | Shell scripts versus Python control-plane responsibilities |
| [v0-alpha-release-plan-v3.html](docs/v0-alpha-release-plan-v3.html) | Phase 0 release gates and blueprint V1 migration order |
| [v0-alpha-implementation-status.html](docs/v0-alpha-implementation-status.html) | v3 plan implementation status |
| [release-notes-v0.1.0.html](docs/release-notes-v0.1.0.html) | v0.1.0 release notes and known limits |

## Contributing

Development happens on `dev`; `main` is the protected, release-tagged branch and is never
committed to directly.

```bash
git checkout -b feat/your-change origin/dev
# ...work, commit...
git push -u origin feat/your-change   # then open a PR into dev
```

Please keep the suite green before opening a PR:

```bash
uv sync --dev && source .venv/bin/activate
pytest -p no:cacheprovider -q
ruff check src tests
```

## License

[MIT](LICENSE) © JasonZQH
