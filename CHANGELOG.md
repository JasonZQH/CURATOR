# Changelog

All notable changes to Curator are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Phase 0

First public release. Local, single-writer, sequential — the evidence-driven base the V1
runtime kernel builds on.

### Added
- **The Phase 0 control loop.** An accepted goal compiles a single-writer workflow:
  `writer → deterministic verifier → fresh-context reviewer → human confirmation gate`.
- **Deterministic scheduler.** Curator — not the model — decides continue, retry, pause,
  stop, and resume; providers only produce typed output.
- **Real provider CLIs.** Async streaming drivers for **Claude Code** and **Codex**; prompt
  and context are passed via stdin (excluded from argv). No synthetic/fallback provider.
- **Provider-neutral role slots.** Bind any provider to `writer.default` / `reviewer.default`
  (e.g. Claude Code writer + Codex reviewer) and switch or recover a runtime without changing
  the task's execution identity.
- **Durable SQLite ledger.** Iterations, decisions-with-reason, provider runs, evidence refs,
  pauses, and resumes are queryable rows under `.curator/`. Every change is attributed.
- **Deterministic verification with hashed evidence.** The loop exits on real command results,
  and the writer's `git diff` is SHA-256-hashed as tamper-evident implementation evidence.
- **Clean-tree guard + opt-in `/resume stash`.** The first writer dispatch refuses a dirty
  tree so its diff stays attributable; `/resume stash` tucks your uncommitted work aside
  (excluding `.curator/`) and runs the writer on a clean baseline (restore with `git stash pop`).
- **Pause / resume from durable state.** `/resume` rebuilds execution state from the ledger;
  pauses cover missing provider, dirty workspace, handoff, and missing verification.
- **Learning memory.** Retries, failures, and pauses are distilled into memory entries and
  injected into future context packages; inspect with `/memory`.
- **Interactive shell + full-screen TUI.** Natural-language requests, a slash-command palette,
  first-run trust/setup, persistent history, Tab completion, and Shift+Enter continuation.
- **CLI.** `curator init | setup | provider add|list | status | doctor | reset | contract
  validate`, and a bare `curator` to open the shell.

### Known limitations
Serial single-writer (local `flock`, no cross-host coordination); the decisions/evidence rows
— not the provider transcript — are the system of record; macOS primary, Linux in CI, Windows
via WSL2 only.

[0.1.0]: https://github.com/JasonZQH/CURATOR/releases/tag/v0.1.0
