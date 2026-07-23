"""Tool-call provider events must carry the real command/paths, redacted and bounded."""

from curator.providers.claude_code import ClaudeCodeDriver
from curator.providers.codex_cli import CodexCliDriver
from curator.providers.events import ProviderEventKind
from curator.tui.format import render_provider_event


def test_codex_command_execution_event_carries_the_command(tmp_path):
    """Verify a Codex command_execution event exposes the command it ran."""
    driver = CodexCliDriver(tmp_path)
    line = (
        '{"type": "item.completed", "item": {"type": "command_execution", '
        '"command": "pytest -q", "exit_code": 0}}'
    )
    event = driver.parse_event(line, "harness-001", 1)

    assert event is not None
    assert event.kind is ProviderEventKind.TOOL_CALL
    assert event.label == "command_execution"
    assert "pytest -q" in event.payload["detail"]


def test_codex_file_change_event_names_the_paths(tmp_path):
    """Verify a Codex file_change event exposes the touched paths."""
    driver = CodexCliDriver(tmp_path)
    line = (
        '{"type": "item.completed", "item": {"type": "file_change", '
        '"changes": [{"path": "src/app.py"}, {"path": "README.md"}]}}'
    )
    event = driver.parse_event(line, "harness-001", 2)

    assert event is not None
    assert "src/app.py" in event.payload["detail"]


def test_codex_tool_detail_is_redacted(tmp_path):
    """Verify secrets in a command are scrubbed before they reach the event."""
    driver = CodexCliDriver(tmp_path)
    line = (
        '{"type": "item.completed", "item": {"type": "command_execution", '
        '"command": "deploy --token=sk-abcdef0123456789abcdef"}}'
    )
    event = driver.parse_event(line, "harness-001", 3)

    assert "sk-abcdef0123456789abcdef" not in event.payload["detail"]
    assert "[REDACTED]" in event.payload["detail"]


def test_claude_tool_use_event_carries_the_input(tmp_path):
    """Verify a Claude tool_use event exposes its command/file input, not just the name."""
    driver = ClaudeCodeDriver(tmp_path)
    line = (
        '{"type": "assistant", "message": {"content": ['
        '{"type": "tool_use", "name": "Bash", "input": {"command": "ruff check src"}}]}}'
    )
    event = driver.parse_event(line, "harness-001", 1)

    assert event is not None
    assert event.kind is ProviderEventKind.TOOL_CALL
    assert event.label == "Bash"
    assert "ruff check src" in event.payload["detail"]


def test_codex_turn_completed_reports_tokens_and_provider(tmp_path):
    """Verify a Codex turn.completed event carries the provider and its token total."""
    driver = CodexCliDriver(tmp_path)
    line = '{"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 600}}'
    event = driver.parse_event(line, "harness-001", 9)

    assert event is not None
    assert event.kind is ProviderEventKind.USAGE
    assert event.payload["provider"] == "codex"
    assert event.payload["tokens"] == 1500


def test_claude_result_reports_tokens_and_provider(tmp_path):
    """Verify a Claude result event carries the provider and its token total."""
    driver = ClaudeCodeDriver(tmp_path)
    line = '{"type": "result", "usage": {"input_tokens": 1000, "output_tokens": 500}}'
    event = driver.parse_event(line, "harness-001", 9)

    assert event is not None
    assert event.kind is ProviderEventKind.USAGE
    assert event.payload["provider"] == "claude-code"
    assert event.payload["tokens"] == 1500


def test_render_tool_call_shows_the_detail():
    """Verify the TUI renders the tool-call detail next to the tool name."""
    from curator.providers.events import ProviderEvent

    event = ProviderEvent(
        kind=ProviderEventKind.TOOL_CALL,
        provider_run_id="p1",
        sequence=1,
        label="command_execution",
        payload={"detail": "pytest -q"},
    )
    rendered = render_provider_event(event)

    assert "command_execution" in rendered
    assert "pytest -q" in rendered
