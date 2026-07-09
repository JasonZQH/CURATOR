"""Generate project, convention, and role memory files."""

from pathlib import Path

from curator.core.enums import RoleName
from curator.core.schema import CuratorPaths


def _memory_document(title: str, what: str, how: str, why: str, future: str) -> str:
    """Render one default memory document in the required HTML shape."""
    return (
        f"<h1>{title}</h1>\n"
        "<section>\n"
        "<h2>What</h2>\n"
        f"<p>{what}</p>\n"
        "</section>\n"
        "<section>\n"
        "<h2>How</h2>\n"
        f"<p>{how}</p>\n"
        "</section>\n"
        "<section>\n"
        "<h2>Why</h2>\n"
        f"<p>{why}</p>\n"
        "</section>\n"
        "<section>\n"
        "<h2>Future improvements/considerations/trade-offs</h2>\n"
        f"<p>{future}</p>\n"
        "</section>\n"
    )


def default_memory_documents() -> dict[str, str]:
    """Return default Phase 0 memory documents keyed by logical name."""
    return {
        "project": _memory_document(
            "Project memory",
            "Shared project facts that every Curator role can inspect.",
            "Keep stable project context here after human review.",
            "A file-backed memory keeps state visible outside any single chat session.",
            "Summaries should stay concise and should not replace source files or tests.",
        ),
        "conventions": _memory_document(
            "Project conventions",
            "Shared engineering conventions for Curator role work.",
            "Record commands, style rules, and workflow norms as they become stable.",
            "Explicit conventions reduce repeated coordination cost across sessions.",
            "Some conventions may later move into tool-specific config files.",
        ),
        "roles/pm": _memory_document(
            "PM memory",
            "Persistent planning context for the PM role.",
            "Capture recurring planning preferences and product constraints.",
            "PM memory helps future plans stay consistent with prior decisions.",
            "Avoid turning this into a backlog; keep actionable plans in sessions.",
        ),
        "roles/engineer": _memory_document(
            "Engineer memory",
            "Persistent implementation context for the Engineer role.",
            "Capture stable codebase facts, command notes, and integration constraints.",
            "Engineer memory lowers rediscovery work during implementation.",
            "Do not duplicate code comments or replace tests with prose.",
        ),
        "roles/qa": _memory_document(
            "QA memory",
            "Persistent validation context for the QA role.",
            "Capture known verification commands and quality risks.",
            "QA memory makes validation repeatable across future sessions.",
            "Keep this focused on evidence and avoid vague quality preferences.",
        ),
    }


def _path_for_memory(paths: CuratorPaths, name: str) -> Path:
    """Return the filesystem path for a logical memory document name."""
    if name == "project":
        return paths.memory_dir / "project.md"
    if name == "conventions":
        return paths.memory_dir / "conventions.md"
    if name == "roles/pm":
        return paths.role_memory_file(RoleName.PM)
    if name == "roles/engineer":
        return paths.role_memory_file(RoleName.ENGINEER)
    if name == "roles/qa":
        return paths.role_memory_file(RoleName.QA)

    raise ValueError(f"Unknown memory document: {name}")


def _write_new_file(path: Path, content: str) -> bool:
    """Write a file only when it does not already exist."""
    if path.exists():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def write_default_memory(paths: CuratorPaths) -> list[Path]:
    """Create missing default memory files and return the files written."""
    written: list[Path] = []

    for name, content in default_memory_documents().items():
        path = _path_for_memory(paths, name)
        if _write_new_file(path, content):
            written.append(path)

    return written
