"""Drive the Codex CLI as a streaming provider."""

from pathlib import Path

from curator.core.enums import ProviderErrorKind, ProviderName
from curator.core.schema import HarnessRunSpec
from curator.harness.context import render_prompt
from curator.harness.workspace import WorkspaceBaseline, capture_baseline
from curator.providers.cli_common import build_cli_provider_response
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse
from curator.providers.driver import SubprocessDriver
from curator.providers.events import OUTPUT_CHUNK_MAX_CHARS, ProviderEvent, ProviderEventKind
from curator.runtime.action_policy import ActionPolicy
from curator.runtime.permissions import codex_sandbox_args


class CodexCliDriver(SubprocessDriver):
    """Run `codex exec --json` behind the async driver protocol."""

    provider_name = ProviderName.CODEX

    def __init__(self, project_root: Path | str, slot: str | None = None, **kwargs) -> None:
        """Bind the driver to one project workspace and functional slot."""
        super().__init__(project_root, **kwargs)
        self.slot = slot
        self._baselines: dict[str, WorkspaceBaseline] = {}
        self._final_text: dict[str, str] = {}

    def build_argv(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> list[str]:
        """Return the `codex exec --json` argv with policy-derived sandbox flags."""
        # The scheduler owns clean-tree enforcement (only on the loop's first
        # writer dispatch); the driver just records the baseline for diffing.
        self._baselines[spec.id] = capture_baseline(self.project_root)
        policy = ActionPolicy.for_project(self.project_root)
        _ = request
        return [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            *codex_sandbox_args(policy, self.slot),
        ]

    def build_prompt(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> str:
        """Render the context package prompt for Codex stdin."""
        _ = spec
        return render_prompt(request, self.slot)

    def parse_event(
        self, line: str, provider_run_id: str, sequence: int
    ) -> ProviderEvent | None:
        """Map one Codex JSONL event to a provider event."""
        payload = self.parse_json_line(line)
        if payload is None:
            return None

        event_type = str(payload.get("type", ""))
        item = payload.get("item", {}) if isinstance(payload.get("item"), dict) else {}
        item_type = str(item.get("type", ""))

        if event_type.startswith("item"):
            if item_type in {"command_execution", "file_change", "patch"}:
                return ProviderEvent(
                    kind=ProviderEventKind.TOOL_CALL,
                    provider_run_id=provider_run_id,
                    sequence=sequence,
                    label=item_type,
                    payload={"event": event_type},
                )
            text = item.get("text") or item.get("message")
            if isinstance(text, str) and text:
                self._final_text[provider_run_id] = text
            return ProviderEvent(
                kind=ProviderEventKind.OUTPUT_CHUNK,
                provider_run_id=provider_run_id,
                sequence=sequence,
                    payload={"event": event_type, "text": str(text)[:OUTPUT_CHUNK_MAX_CHARS]},
            )
        if event_type in {"turn.completed", "turn.failed"}:
            return ProviderEvent(
                kind=ProviderEventKind.USAGE,
                provider_run_id=provider_run_id,
                sequence=sequence,
                payload={"event": event_type},
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
        """Convert the observed Codex run into a typed response."""
        if returncode != 0:
            lowered = stderr_tail.lower()
            error_kind = (
                ProviderErrorKind.PERMISSION_DENIED
                if "auth" in lowered or "login" in lowered
                else ProviderErrorKind.PROVIDER_UNAVAILABLE
            )
            return self._failed_response(
                request, error_kind, stderr_tail or "codex exited non-zero"
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
