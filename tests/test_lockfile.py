"""Verify local project write-lock reentrancy, threading, and process contention."""

import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from curator.runtime.lockfile import ProjectLockedError, project_write_lock


def test_project_write_lock_is_reentrant_in_one_process(tmp_path):
    """Verify nested app mutation calls share one held lock."""
    with project_write_lock(tmp_path):
        with project_write_lock(tmp_path):
            assert (tmp_path / ".curator" / "runtime.lock").exists()
    with project_write_lock(tmp_path):
        pass


def test_project_write_lock_rejects_a_second_thread(tmp_path):
    """Verify a TUI worker thread cannot bypass the owning thread's lock."""
    rejected: list[Exception] = []

    def contend() -> None:
        """Attempt a concurrent mutation from another local thread."""
        try:
            with project_write_lock(tmp_path):
                pass
        except Exception as error:  # noqa: BLE001 - assert the public lock error below
            rejected.append(error)

    with project_write_lock(tmp_path):
        thread = threading.Thread(target=contend)
        thread.start()
        thread.join()

    assert len(rejected) == 1
    assert "worker owns this project" in str(rejected[0])


def test_project_write_lock_rejects_a_second_process(tmp_path):
    """Verify a separate Curator process is denied while the lock is held."""
    script = """
from pathlib import Path
import sys
from curator.runtime.lockfile import project_write_lock

with project_write_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    input()
"""
    env = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(ProjectLockedError, match="Another Curator is running"):
            with project_write_lock(tmp_path):
                pass
        process.stdin.write("\n")  # type: ignore[union-attr]
        process.stdin.flush()  # type: ignore[union-attr]
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
