"""Verify Curator path names are exposed consistently."""

from curator.core.models.paths import CuratorPaths
from curator.core.paths import build_curator_paths
from curator.core.schema import CuratorPaths as FacadeCuratorPaths


def test_build_curator_paths_exposes_curator_named_fields(tmp_path):
    """Verify the preferred path builder returns Curator-named fields."""
    paths = build_curator_paths(tmp_path)

    assert isinstance(paths, CuratorPaths)
    assert paths.curator_dir == tmp_path / ".curator"
    assert paths.database == tmp_path / ".curator" / "curator.sqlite"


def test_schema_facade_exports_curator_paths():
    """Verify schema facade exports the Curator path model."""
    assert FacadeCuratorPaths is CuratorPaths
