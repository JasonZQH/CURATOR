"""The busy indicator shows a music-production word for the current loop phase."""

import asyncio
import sqlite3

from curator.core.enums import LoopStepType
from curator.tui.shell_app import _DEFAULT_PHASE_WORD, _PHASE_WORDS, CuratorShellApp


def test_every_loop_step_has_a_phase_word():
    """Verify each loop step maps to a music-production word (no bare 'working')."""
    for step in LoopStepType:
        assert step.value in _PHASE_WORDS, f"no phase word for {step.value}"
    assert _PHASE_WORDS["implement"] == "Arranging"
    assert _PHASE_WORDS["review"] == "Auditioning"
    assert "working" not in {word.lower() for word in _PHASE_WORDS.values()}


def _insert_running_iteration(database, step_value: str) -> None:
    """Write one RUNNING loop iteration so the status read has a current phase."""
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO loop_iterations "
        "(id, loop_run_id, session_id, task_id, sequence, step_type, role, status, "
        "started_at, completed_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, NULL, '{}')",
        ("iter-1", "loop-1", "sess-1", "task-1", 1, step_value, "engineer",
         "2026-07-23T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def test_current_phase_word_reads_the_running_step(tmp_path, monkeypatch):
    """Verify the working line reflects the step_type of the active iteration."""
    from curator.app import write_init_state

    write_init_state(tmp_path)
    from curator.core.paths import build_curator_paths

    database = build_curator_paths(tmp_path).database
    _insert_running_iteration(database, LoopStepType.REVIEW.value)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._current_phase_word() == "Auditioning"
            assert "Auditioning" in app._working_line()

    asyncio.run(run())


def test_current_phase_word_defaults_before_any_iteration(tmp_path, monkeypatch):
    """Verify the working line falls back to the default word with no running step."""
    from curator.app import write_init_state

    write_init_state(tmp_path)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._current_phase_word() == _DEFAULT_PHASE_WORD

    asyncio.run(run())


def test_working_line_shows_provider_token_usage(tmp_path):
    """Verify the working line shows the current provider and its compact token usage."""
    from curator.providers.events import ProviderEvent, ProviderEventKind

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._on_provider_event(
                ProviderEvent(
                    kind=ProviderEventKind.STARTED,
                    provider_run_id="p",
                    sequence=0,
                    payload={"provider": "codex"},
                )
            )
            app._on_provider_event(
                ProviderEvent(
                    kind=ProviderEventKind.USAGE,
                    provider_run_id="p",
                    sequence=1,
                    payload={"provider": "codex", "tokens": 1500},
                )
            )
            assert "codex: 1.5k" in app._working_line()

    asyncio.run(run())
