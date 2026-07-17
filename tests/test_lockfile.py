"""Verify local project write-lock reentrancy and release."""

from curator.runtime.lockfile import project_write_lock


def test_project_write_lock_is_reentrant_in_one_process(tmp_path):
    """Verify nested app mutation calls share one held lock."""
    with project_write_lock(tmp_path):
        with project_write_lock(tmp_path):
            assert (tmp_path / ".curator" / "runtime.lock").exists()
    with project_write_lock(tmp_path):
        pass
