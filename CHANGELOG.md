# Changelog

All notable changes to Curator are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Curator's own state is off limits to a run, and tampering is caught.** `.curator/`
  holds the role contracts, the loop templates, and the ledger, and it sits inside the one
  writable root a provider is given — while being invisible to every diff-based check
  (the repo gitignores it, `curator init` writes `.curator/.gitignore` with `*`, and the
  workspace guard filters it out of git porcelain). A provider that rewrote its own
  contract therefore left no trace. Three layers now cover it: Claude Code is denied those
  paths at the argv layer, `ActionPolicy` carves `.curator` out of the writable root for
  in-process callers, and the contract files are hashed around every dispatch — if they
  move while a provider is running, the loop pauses for a human and **that step's evidence
  is refused**. The hash check is the only one of the three that works on the Codex seat,
  which has no way to deny a subpath of the root it can write.

### Changed
- **Provider permissions are default-deny.** The check named the read-only slots, so any
  slot that was not literally `reviewer` or `maindeck` — a typo, a slot added by a later
  version, or the `None` a step compiles with when it declares no slot — fell through to
  workspace-write. It is now an allowlist: only the `writer` slot may write, everything
  else is read-only on both providers.
- **The writer gets named git verbs instead of `Bash(git *)`.** The wildcard also granted
  `git config`, `git checkout`, and `git worktree`, and left the `git push` denial resting
  on prefix matching alone.

### Fixed
- **Every evidence kind now carries a real digest.** Ordinary provider output was recorded
  with `content_hash` set to `sha256:<run id>:<kind>` — a string shaped like a digest that
  hashed nothing — and review evidence, the kind the shipped CLI seats actually produce,
  carried no hash at all. Both are now a SHA-256 over the content the reference describes,
  in a canonical sorted-key JSON form that reproduces outside Curator. The four producers
  share one definition of that form, so a content-addressed store can rely on it.
- **Resume no longer hands an exhausted step a fresh retry budget.** The retry counters
  lived only in memory, so resuming a paused loop reset them: a step that had already spent
  its budget could be retried again, and because the loop no longer considered it a retry
  attempt, the failing validation evidence stopped being injected into its next context.
  Each scheduled retry now records its target on the decision, and resume rebuilds the
  spent budget by folding those rows.
- **Resume runs under the project's own role contracts.** It passed none, so the resumed
  half of a loop silently fell back to the built-in contracts while the first half ran on
  the edited `.curator/team` files.
- **Parallel Claude tool calls are no longer dropped.** Claude batches several `tool_use`
  blocks into one assistant message; only the first was read, so the activity block
  undercounted calls and the files touched by the rest were never shown.
- **The ledger records what a tool actually did.** The tool-call detail — the command run
  or the file touched — was dropped on the way to the ledger, so "who changed which files"
  was visible live and unanswerable afterwards from the durable record. It is redacted
  before it is stored.
- **`curator init`, `setup`, `provider add`, and `reset` take the project write lock.**
  They took no lock at all, so a second terminal could archive the ledger or rewrite
  provider bindings underneath a loop that was mid-run with the database open. They now
  refuse with a clear message instead of racing.

## [0.1.2] — 2026-07-28

### Added
- **The ledger is backed up before a schema migration.** Opening `.curator/` with a newer
  Curator applies pending migrations automatically; it now copies the ledger to
  `.curator/archive/…-pre-migration.sqlite` first. The copy uses SQLite's online backup
  API rather than a file copy, so data still sitting in the write-ahead log is preserved.
  A ledger with nothing to migrate — the usual case, since every command opens it — is not
  copied.
- **`curator doctor` reports pending migrations and the newest backup.** It lists what the
  next open will apply without applying it, and prints a ready-to-paste `cp` command to
  restore the most recent backup. The backup lookup reads the directory, not the ledger, so
  it still answers when the ledger will not open.

### Fixed
- **A failed backup is never offered as a restore point.** `sqlite3.connect` creates the
  destination up front, so a backup interrupted by a full disk, an I/O error, or a killed
  process left a truncated file carrying the real name. Being the newest, it became what
  `curator doctor` advertised as the ledger to restore — and copying it over a live ledger
  would have destroyed it. Backups are now written under a name the restore path ignores and
  renamed into place only once complete, and an unusable file is never advertised.
- **A failed migration no longer leaves a half-migrated ledger.** Pending migrations and
  their `schema_version` rows now share one transaction, so a failure rolls the schema
  changes back with it instead of stopping in an intermediate state and raises
  `CuratorStateError`. Previously each migration committed on its own.

## [0.1.1] — 2026-07-28

### Fixed
- **Codex tool-call counts in the activity block.** One Codex command emits several
  lifecycle events (`item.started`, then `item.completed`) for the same call, and the
  coalesced `⏺ label ×N` block counted each of them — reading about 2× high. Events are now
  folded by item id, so one logical call counts once. Claude Code (one event per call) and
  the ledger are unchanged. ([#26](https://github.com/JasonZQH/CURATOR/issues/26))

### Changed
- **Docs numbering unified.** The "Phase 0/1/2/3" and "V1.1–V1.6" ladders are folded into
  the single `v0.1.x` roadmap; the affected design docs carry a mapping banner and the new
  `pi · Curator · Orca architecture` doc is linked from every page as the canonical roadmap.

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

[0.1.2]: https://github.com/JasonZQH/CURATOR/releases/tag/v0.1.2
[0.1.1]: https://github.com/JasonZQH/CURATOR/releases/tag/v0.1.1
[0.1.0]: https://github.com/JasonZQH/CURATOR/releases/tag/v0.1.0
