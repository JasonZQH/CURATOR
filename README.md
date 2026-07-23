<div align="center">

<img src="docs/assets/curator-logo.png" alt="Curator" width="560">

**The coding-agent workbench where the scheduler — not the model — stays in control.**

Curator orchestrates real provider CLIs like **Claude Code** and **Codex** through an
auditable control plane: it plans an accepted goal, dispatches a single writer, gates the
loop on **deterministic verification**, runs a **fresh-context reviewer**, and pauses for
you at a human confirmation gate — recording every decision, evidence ref, and pause to a
durable local ledger you can resume from.

[![CI](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml/badge.svg)](https://github.com/JasonZQH/CURATOR/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Built by JasonZQH](https://img.shields.io/badge/built%20by-JasonZQH-orange.svg)](https://github.com/JasonZQH)

</div>

---

## Why Curator

Run Claude Code or Codex directly and the important things — *why* a run continued, retried,
or stopped; *who* actually wrote which change; *how* to pick up a half-finished task
tomorrow — are trapped inside a chat transcript. Switch providers and you start over, with a
different UI and no shared record. Curator keeps the model doing what it is good at — writing
code — while a **deterministic scheduler owns retry, pause, stop, and resume** across every
provider. When a run fails, stalls, needs a permission, or drifts in scope, you see exactly
why, and you can resume it later from durable state instead of starting over.

| | |
|---|---|
| **Real providers, not a wrapper** | Dispatches the Claude Code and Codex CLIs behind an async streaming driver — tool calls, permissions, and output flow through as typed events, not an opaque chat. Prompt/context go via stdin, never argv. |
| **The scheduler owns control flow** | Providers produce typed output; Curator alone decides continue, retry, pause, stop, and resume. Control flow never hides inside a transcript. |
| **Deterministic verification** | The loop exits on real test/command results with content-hashed evidence — not on a model's self-reported "looks good." |
| **Fresh-context, cross-provider review** | A second provider reviews the implementation and verification evidence *without* the writer's context and surfaces what the author cannot see. Advisory to the human confirm gate — it informs, it does not silently block. |
| **Everything is on the ledger** | Every iteration, decision-with-reason, provider run, evidence ref, pause, and resume is a durable SQLite row under `.curator/`. Runs are auditable, and every change is attributed to the provider that made it. |
| **Resume from anywhere** | Paused a loop yesterday? `/resume` rebuilds execution state from the ledger and continues — a confirm-gate "yes" finishes it, anything else re-runs the writer with your guidance. |
| **Mix providers under one control plane** | Provider-neutral role slots let you bind, say, Claude Code as the writer and Codex as the reviewer — same auditable loop, either engine. |
| **Local-first, no fallback theater** | No synthetic provider. A missing or broken CLI blocks setup and an unconfigured run pauses with next steps — never fake success. |

## How a run works

1. Your text becomes a durable goal draft, then an accepted goal revision.
2. Curator compiles a single-writer Phase 0 workflow session.
3. The **writer** provider gets a context package through stdin (prompt text is excluded from argv).
4. The **verifier** runs discovered or explicit commands and produces hashed evidence.
5. A fresh-context **reviewer** provider assesses the implementation and verification.
6. A **human confirmation gate** pauses before delivery is marked done.
7. Every step lands on the ledger, so `/resume` can continue a paused loop later.

Everything above is **Phase 0** — local, single-writer, sequential. The broader V1 blueprint
(dependency-aware scheduling, parallel workers, separate Agent/Runtime/Execution identities,
provider-native TUI handoff) is a **migration target, not current capability**; this README
describes only what ships today.

## Getting started

**Prerequisites.** A logged-in provider CLI on your `PATH` — [Claude Code](https://code.claude.com/docs)
or [Codex](https://developers.openai.com/codex). Curator drives the real CLI; it never fakes a provider.

**Install** — globally, the same way you'd install `claude-code` or `codex`:

```bash
# One line — bootstraps uv, then installs the curator CLI (macOS / Linux / WSL2)
curl -fsSL https://raw.githubusercontent.com/JasonZQH/CURATOR/main/install.sh | sh
```

Or with pipx / uv:

```bash
pipx install "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0"
uvx --from "git+https://github.com/JasonZQH/CURATOR.git@v0.1.0" curator
```

> Pin a released tag (`@v0.1.0`) for a reproducible install, or drop it to track `main`.
> On Windows, run inside WSL2.

**Open it** — from any project directory:

```bash
curator
```

That drops you into the natural-language shell. First run walks you through trust, roles, and
connecting a provider; then just say what you want to work on. Bind providers to functional
slots and go:

```
/agent bind writer.default claude-code
/agent bind reviewer.default codex
> add a --json flag to the export command
```

Small requests start immediately; `/gate on` reviews the goal proposal first.

> **Heads up:** Curator dispatches a real CLI with workspace-write permission. It blocks a
> dirty git tree before a writer runs so changes are never misattributed — commit, stash, or
> reply `/resume stash` to tuck your changes aside automatically (restore later with
> `git stash pop`).

## Versions

**Released**

| Version | Status | What it is |
|---|---|---|
| **v0.1.0** | Current | Phase 0 — local · single-writer · sequential. `Goal → writer → deterministic verifier → fresh-context reviewer → human confirm`, on a durable SQLite ledger. Opt-in `/resume stash` for the clean-tree guard. |

v0.1.0 highlights: full-screen first-run trust & setup, keyboard-selectable slash commands and
proposal actions, PM/Engineer/Reviewer seat labels, persistent history with Tab completion and
Shift+Enter continuation.

**Roadmap** — planned targets, not current capability:

| Milestone | Focus |
|---|---|
| V1.1 · Canonical Model | Durable Project / Session / Goal / Task / Dependency entities, append-only events |
| V1.2 · Runtime Registry | Agent & Execution runtimes, leases, heartbeats, capability probes |
| V1.3 · Scheduler | Goal → Task DAG, ready queue, retry/approval policy, workspace ownership |
| V1.4 · Runtime UX | Control Desk, tmux backend, provider-TUI focus/sync |
| V1.5 · Recovery | Handoff snapshots, machine-restart recovery, artifact replay |
| V1.6 · Parallel Workers | Up to 4 local parallel workers on independent ready tasks |

Full history in [CHANGELOG.md](CHANGELOG.md).

## Commands

**Terminal — `curator …`**

| Command | Description |
|---|---|
| `curator` | Open the natural-language shell/TUI for the current project |
| `curator init` | Create local `.curator/` state (`--yes` to write, `-C` to target a dir) |
| `curator setup` | Guided setup: roles → providers → login |
| `curator provider add <name>` | Detect and register a provider CLI (`claude-code` / `codex`) |
| `curator provider list` | List configured provider profiles |
| `curator status` | Show current project state |
| `curator doctor` | Run environment and readiness checks |
| `curator reset` | Archive the ledger and clear runtime state (`--hard` removes `.curator/`) |
| `curator contract validate` | Validate editable role contracts |
| `curator --version` | Print the version |

**In-shell — slash commands**

| Area | Commands |
|---|---|
| Start work | type a request · `/gate on\|off` · `yes` / `no` / `edit <text>` |
| Watch progress | `/workbench` · `/node current` · `/evidence` · `/status` |
| Handle pauses | `/resume <answer>` · `/resume stash` · `/resume continue` · `/revise <scope>` · `/cancel` |
| Providers & slots | `/providers` · `/provider add <name>` · `/agents` · `/agent bind <slot> <provider>` |
| Inspect & learn | `/memory` · `/history` · `/sessions` · `/help` · `/help all` |

`/help` is task-oriented (what to do next); `/help all` lists every command. The full-screen
TUI adds Up/Down history, Tab completion, Shift+Enter/Ctrl+J continuation lines, Esc
interruption, and two-stage Ctrl+C shutdown.

## Known limitations

Phase 0 is deliberately narrow. Where a claim above could be read more broadly than the code
delivers, the boundary is spelled out here:

- **Serial, single-writer.** One writer runs at a time; there is no parallel worker or
  dependency-aware DAG yet. Project writes are serialized through a local `flock`
  (`.curator/runtime.lock`), which does not coordinate across network filesystems.
- **The auditable system-of-record is the decisions, not the transcript.** The durable,
  queryable truth is the iteration / decision-with-reason / evidence / provider-run rows.
  Provider stdout is persisted as `OUTPUT_CHUNK` rows that are a **redacted, continuous
  delta** of the stream — they do not map one-to-one to source chunks and the transcript is
  not replayed. `/resume` rebuilds execution state from the decision/evidence rows.
- **Cancellation boundary.** The bundled Claude Code and Codex adapters convert a cancel into
  a typed error, and that run's streamed transcript is preserved on the ledger. A bare
  `asyncio.CancelledError` propagating straight through rolls back the in-flight streamed
  batch by design (the step commits its transcript in one transaction).
- **Platform.** macOS is the primary test target, Linux runs in CI, and Windows is
  unsupported (use WSL2).

## Contributing

Curator is developed on the `dev` branch; `main` is protected and release-tagged. Anyone can
[open an issue](https://github.com/JasonZQH/CURATOR/issues/new/choose); invited contributors
open pull requests into `dev`. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the workflow,
local development setup, and how to run the test suite.

## License

[MIT](LICENSE) © JasonZQH
