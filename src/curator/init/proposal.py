"""Build reviewable initialization proposals before writing state."""

from pathlib import Path

from curator.core.enums import RoleName
from curator.core.paths import build_curator_paths
from curator.core.schema import CuratorPaths, InitProposal
from curator.init.detector import detect_project_type


def phase0_proposed_files(paths: CuratorPaths) -> list[Path]:
    """List the Phase 0 files that init would create after approval."""
    return [
        paths.role_file(RoleName.PM),
        paths.role_contract_file(RoleName.PM),
        paths.role_file(RoleName.ENGINEER),
        paths.role_contract_file(RoleName.ENGINEER),
        paths.role_file(RoleName.QA),
        paths.role_contract_file(RoleName.QA),
        paths.memory_dir / "project.md",
        paths.memory_dir / "conventions.md",
        paths.role_memory_file(RoleName.PM),
        paths.role_memory_file(RoleName.ENGINEER),
        paths.role_memory_file(RoleName.QA),
        paths.curator_dir / ".gitignore",
        paths.database,
    ]


def build_init_proposal(project_root: Path | str) -> InitProposal:
    """Build a reviewable init proposal without writing project state."""
    root = Path(project_root)
    paths = build_curator_paths(root)

    return InitProposal(
        project_root=root,
        paths=paths,
        detected_project_type=detect_project_type(root),
        proposed_files=phase0_proposed_files(paths),
    )


def render_init_proposal(proposal: InitProposal) -> str:
    """Render an init proposal as terminal-friendly text."""
    lines = [
        "Curator init proposal",
        "",
        f"Project root: {proposal.project_root}",
        f"Detected project type: {proposal.detected_project_type or 'unknown'}",
        "",
        "Will create:",
    ]

    for path in proposal.proposed_files:
        lines.append(f"- {path.relative_to(proposal.project_root)}")

    return "\n".join(lines)
