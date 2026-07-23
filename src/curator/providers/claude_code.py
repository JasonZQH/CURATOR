"""Drive the Claude Code CLI as a streaming provider."""

from pathlib import Path

from curator.core.enums import ProviderErrorKind, ProviderName
from curator.core.schema import HarnessRunSpec
from curator.harness.context import render_prompt
from curator.harness.workspace import WorkspaceBaseline, capture_baseline
from curator.providers.cli_common import build_cli_provider_response, usage_tokens
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse
from curator.providers.driver import SubprocessDriver
from curator.providers.events import OUTPUT_CHUNK_MAX_CHARS, ProviderEvent, ProviderEventKind
from curator.providers.redact import redact_secrets
from curator.runtime.action_policy import ActionPolicy
from curator.runtime.permissions import claude_permission_args

# Cap the tool-call detail (command or file path) shown in the transcript.
_TOOL_DETAIL_MAX = 200


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
        # The scheduler owns clean-tree enforcement (only on the loop's first
        # writer dispatch); the driver just records the baseline for diffing.
        self._baselines[spec.id] = capture_baseline(self.project_root)
        policy = ActionPolicy.for_project(self.project_root)
        _ = request
        return [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            *claude_permission_args(policy, self.slot),
        ]

    def build_prompt(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> str:
        """Render the context package prompt for Claude stdin."""
        _ = spec
        return render_prompt(request, self.slot)

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
            tool = _tool_use(payload)
            if tool is not None:
                name, detail = tool
                return ProviderEvent(
                    kind=ProviderEventKind.TOOL_CALL,
                    provider_run_id=provider_run_id,
                    sequence=sequence,
                    label=name,
                    payload={"type": message_type, "detail": detail},
                )
            return ProviderEvent(
                kind=ProviderEventKind.OUTPUT_CHUNK,
                provider_run_id=provider_run_id,
                sequence=sequence,
                payload={"type": message_type, "text": text[:OUTPUT_CHUNK_MAX_CHARS]},
            )
        if message_type == "result":
            result_text = payload.get("result")
            if isinstance(result_text, str) and result_text:
                self._final_text[provider_run_id] = result_text
            usage_payload = {
                "subtype": payload.get("subtype", ""),
                "provider": self.provider_name.value,
            }
            tokens = usage_tokens(payload)
            if tokens is not None:
                usage_payload["tokens"] = tokens
            return ProviderEvent(
                kind=ProviderEventKind.USAGE,
                provider_run_id=provider_run_id,
                sequence=sequence,
                payload=usage_payload,
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


def _tool_use(payload: dict) -> tuple[str, str] | None:
    """Return the (name, detail) of the first tool used in an assistant message, if any.

    The detail is a short, redacted summary of the tool input — the command it ran or the
    file it touched — so the transcript shows what happened, not just the tool name.
    """
    message = payload.get("message", {})
    blocks = message.get("content", []) if isinstance(message, dict) else []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = str(block.get("name", "tool"))
            return name, _tool_input_detail(block.get("input"))
    return None


def _tool_input_detail(tool_input: object) -> str:
    """Summarize a tool_use input dict as one redacted, length-bounded line."""
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "path", "pattern", "query", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return redact_secrets(value.strip())[:_TOOL_DETAIL_MAX]
    for key, value in tool_input.items():
        if isinstance(value, str) and value.strip():
            return redact_secrets(f"{key}={value.strip()}")[:_TOOL_DETAIL_MAX]
    return ""
