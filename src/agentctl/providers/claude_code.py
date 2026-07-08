"""Drive the Claude Code CLI as a streaming provider."""

from pathlib import Path

from agentctl.core.enums import ProviderErrorKind, ProviderName
from agentctl.core.schema import HarnessRunSpec
from agentctl.harness.context import render_prompt
from agentctl.harness.workspace import (
    WorkspaceBaseline,
    capture_baseline,
    require_clean_baseline,
)
from agentctl.providers.cli_common import build_cli_provider_response
from agentctl.providers.contracts import ProviderRunRequest, ProviderRunResponse
from agentctl.providers.driver import SubprocessDriver
from agentctl.providers.events import ProviderEvent, ProviderEventKind
from agentctl.runtime.action_policy import ActionPolicy
from agentctl.runtime.permissions import claude_permission_args

DEFAULT_MAX_TURNS = 30


class ClaudeCodeDriver(SubprocessDriver):
    """Run `claude -p` in stream-json mode behind the async driver protocol."""

    provider_name = ProviderName.CLAUDE_CODE

    def __init__(self, project_root: Path | str, slot: str | None = None, **kwargs) -> None:
        """Bind the driver to one project workspace and functional slot."""
        super().__init__(project_root, **kwargs)
        self.slot = slot
        self._baselines: dict[str, WorkspaceBaseline] = {}
        self._final_text: dict[str, str] = {}

    def build_argv(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> list[str]:
        """Return the `claude -p` argv with policy-derived permission flags."""
        baseline = capture_baseline(self.project_root)
        if self.slot == "writer":
            require_clean_baseline(baseline)
        self._baselines[spec.id] = baseline
        policy = ActionPolicy.for_project(self.project_root)
        prompt = render_prompt(request, self.slot)
        return [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--max-turns",
            str(DEFAULT_MAX_TURNS),
            *claude_permission_args(policy, self.slot),
        ]

    def parse_event(
        self, line: str, provider_run_id: str, sequence: int
    ) -> ProviderEvent | None:
        """Map one Claude Code stream-json line to a provider event."""
        payload = self.parse_json_line(line)
        if payload is None:
            return None

        message_type = payload.get("type")
        if message_type == "assistant":
            text = _assistant_text(payload)
            if text:
                self._final_text[provider_run_id] = text
            tool = _tool_use_name(payload)
            if tool:
                return ProviderEvent(
                    kind=ProviderEventKind.TOOL_CALL,
                    provider_run_id=provider_run_id,
                    sequence=sequence,
                    label=tool,
                    payload={"type": message_type},
                )
            return ProviderEvent(
                kind=ProviderEventKind.OUTPUT_CHUNK,
                provider_run_id=provider_run_id,
                sequence=sequence,
                payload={"type": message_type},
            )
        if message_type == "result":
            result_text = payload.get("result")
            if isinstance(result_text, str) and result_text:
                self._final_text[provider_run_id] = result_text
            return ProviderEvent(
                kind=ProviderEventKind.USAGE,
                provider_run_id=provider_run_id,
                sequence=sequence,
                payload={"subtype": payload.get("subtype", "")},
            )
        return None

    def build_response(
        self,
        spec: HarnessRunSpec,
        request: ProviderRunRequest,
        events: list[ProviderEvent],
        returncode: int,
        stderr_tail: str,
    ) -> ProviderRunResponse:
        """Convert the observed Claude Code run into a typed response."""
        if returncode != 0:
            error_kind = (
                ProviderErrorKind.PERMISSION_DENIED
                if "not logged in" in stderr_tail.lower() or "auth" in stderr_tail.lower()
                else ProviderErrorKind.PROVIDER_UNAVAILABLE
            )
            return self._failed_response(
                request, error_kind, stderr_tail or "claude exited non-zero"
            )

        return build_cli_provider_response(
            spec,
            request,
            provider=self.provider_name,
            slot=self.slot,
            final_text=self._final_text.get(spec.id, ""),
            baseline=self._baselines.get(spec.id),
            project_root=self.project_root,
        )


def _assistant_text(payload: dict) -> str:
    """Extract assistant text content from one stream-json message."""
    message = payload.get("message", {})
    blocks = message.get("content", []) if isinstance(message, dict) else []
    texts = [
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return " ".join(text for text in texts if text).strip()


def _tool_use_name(payload: dict) -> str | None:
    """Return the first tool name used in one assistant message, if any."""
    message = payload.get("message", {})
    blocks = message.get("content", []) if isinstance(message, dict) else []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return str(block.get("name", "tool"))
    return None
