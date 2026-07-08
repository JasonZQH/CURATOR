"""Verify Curator path names replace legacy AgentCTL path names safely."""

from agentctl.core.models.paths import AgentctlPaths, CuratorPaths
from agentctl.core.paths import build_agentctl_paths, build_curator_paths
from agentctl.core.schema import CuratorPaths as FacadeCuratorPaths


def test_build_curator_paths_exposes_curator_named_fields(tmp_path):
    """Verify the preferred path builder returns Curator-named fields."""
    paths = build_curator_paths(tmp_path)

    assert isinstance(paths, CuratorPaths)
    assert paths.curator_dir == tmp_path / ".curator"
    assert paths.agentctl_dir == paths.curator_dir
    assert paths.database == tmp_path / ".curator" / "curator.sqlite"


def test_legacy_agentctl_path_names_remain_aliases(tmp_path):
    """Verify legacy path names remain compatible during migration."""
    preferred_paths = build_curator_paths(tmp_path)
    legacy_paths = build_agentctl_paths(tmp_path)

    assert AgentctlPaths is CuratorPaths
    assert FacadeCuratorPaths is CuratorPaths
    assert legacy_paths == preferred_paths
    assert legacy_paths.agentctl_dir == legacy_paths.curator_dir
