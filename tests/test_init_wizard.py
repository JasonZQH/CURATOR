"""Verify Curator initialization behavior."""

from agentctl.core.enums import RoleName
from agentctl.core.paths import build_curator_paths
from agentctl.init.proposal import build_init_proposal, render_init_proposal
from agentctl.init.wizard import create_agentctl_state, create_curator_state


def test_build_init_proposal_lists_phase0_files_without_writing(tmp_path):
    """Verify init proposal describes Curator state without creating it."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    proposal = build_init_proposal(tmp_path)

    assert proposal.project_root == tmp_path
    assert proposal.detected_project_type == "python"
    assert proposal.proposed_files == [
        tmp_path / ".curator" / "team" / "roles" / "pm" / "role.md",
        tmp_path / ".curator" / "team" / "roles" / "pm" / "contract.yaml",
        tmp_path / ".curator" / "team" / "roles" / "engineer" / "role.md",
        tmp_path / ".curator" / "team" / "roles" / "engineer" / "contract.yaml",
        tmp_path / ".curator" / "team" / "roles" / "qa" / "role.md",
        tmp_path / ".curator" / "team" / "roles" / "qa" / "contract.yaml",
        tmp_path / ".curator" / "memory" / "project.md",
        tmp_path / ".curator" / "memory" / "conventions.md",
        tmp_path / ".curator" / "memory" / "roles" / "pm.md",
        tmp_path / ".curator" / "memory" / "roles" / "engineer.md",
        tmp_path / ".curator" / "memory" / "roles" / "qa.md",
        tmp_path / ".curator" / "curator.sqlite",
    ]
    assert not (tmp_path / ".curator").exists()


def test_render_init_proposal_shows_project_and_relative_files(tmp_path):
    """Verify init proposal rendering is reviewable in the terminal."""
    proposal = build_init_proposal(tmp_path)

    output = render_init_proposal(proposal)

    assert "Curator init proposal" in output
    assert f"Project root: {tmp_path}" in output
    assert "Detected project type: unknown" in output
    assert "- .curator/team/roles/pm/role.md" in output
    assert "- .curator/team/roles/pm/contract.yaml" in output
    assert "- .curator/curator.sqlite" in output


def test_create_curator_state_writes_phase0_files_and_database(tmp_path):
    """Verify approved init creates files and the SQLite database."""
    proposal = build_init_proposal(tmp_path)

    result = create_curator_state(proposal)
    paths = build_curator_paths(tmp_path)

    assert paths.curator_dir.exists()
    assert paths.role_file(RoleName.PM).exists()
    assert paths.role_contract_file(RoleName.PM).exists()
    assert paths.role_file(RoleName.ENGINEER).exists()
    assert paths.role_contract_file(RoleName.ENGINEER).exists()
    assert (paths.memory_dir / "project.md").exists()
    assert paths.role_memory_file(RoleName.QA).exists()
    assert paths.database.exists()
    assert result.created_files == proposal.proposed_files


def test_create_curator_state_preserves_existing_files(tmp_path):
    """Verify approved init does not overwrite existing human-edited files."""
    paths = build_curator_paths(tmp_path)
    existing_role = paths.role_file(RoleName.QA)
    existing_role.parent.mkdir(parents=True)
    existing_role.write_text("<h1>custom qa role</h1>\n")
    proposal = build_init_proposal(tmp_path)

    result = create_curator_state(proposal)

    assert existing_role.read_text() == "<h1>custom qa role</h1>\n"
    assert existing_role in result.skipped_files
    assert existing_role not in result.created_files


def test_legacy_create_agentctl_state_name_remains_alias():
    """Verify the old init writer name remains a compatibility alias."""
    assert create_agentctl_state is create_curator_state


def test_create_curator_state_seeds_default_role_pool(tmp_path):
    """Verify init seeds durable role instances before any goal is typed."""
    from agentctl.state.db import connect_database, initialize_database
    from agentctl.state.repositories import load_role_instances

    proposal = build_init_proposal(tmp_path)
    create_curator_state(proposal)

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    role_ids = {role.id for role in load_role_instances(connection)}
    connection.close()

    assert "engineer.1" in role_ids
    assert "qa.1" in role_ids
    assert "pm.coordinator" in role_ids
