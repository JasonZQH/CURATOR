"""Surface a provider CLI's own usage/rate-limit signal clearly, with its reset time.

The CLIs don't expose remaining quota, but when a run actually hits the limit they say
so in their error output. Curator relays that — a clear, provider-attributed pause — rather
than the generic "provider unavailable" it produced before.
"""

from curator.core.enums import (
    HarnessStatus,
    LoopDecisionType,
    LoopStepType,
    ProviderErrorKind,
    ProviderRunStatus,
    RoleName,
    StopCondition,
)
from curator.core.schema import HarnessRunResult, HarnessRunSpec
from curator.loops.compiler import compile_single_writer_plan
from curator.providers.claude_code import ClaudeCodeDriver
from curator.providers.codex_cli import CodexCliDriver
from curator.providers.contracts import ProviderRunRequest
from curator.providers.limits import is_usage_limit, usage_limit_message, usage_limit_reset
from curator.scheduler.decision import decide_runtime


def _spec_request():
    """Return a minimal review-step spec and provider request."""
    spec = HarnessRunSpec(
        id="harness-1",
        session_id="session-1",
        loop_run_id="loop-1",
        iteration_id="iteration-1",
        role=RoleName.QA,
        step_type=LoopStepType.REVIEW,
        task_id="task-1",
    )
    return spec, ProviderRunRequest.from_harness_spec(spec)


def test_is_usage_limit_matches_common_phrasings_only():
    """Verify usage-limit markers match rate/usage phrasing but not benign errors."""
    for text in (
        "Claude usage limit reached",
        "You've hit your rate limit",
        "HTTP 429 Too Many Requests",
        "weekly quota exceeded",
    ):
        assert is_usage_limit(text), text
    for text in ("connection refused", "not logged in", "file not found", ""):
        assert not is_usage_limit(text), text


def test_usage_limit_reset_parses_a_reset_hint():
    """Verify a reset time is extracted from the provider's message when present."""
    assert usage_limit_reset("limit reached, resets at 3:00pm") == "3:00pm"
    assert usage_limit_reset("rate limited; try again in 10 minutes") == "10 minutes"
    assert usage_limit_reset("rate limited") is None


def test_usage_limit_message_names_provider_and_reset():
    """Verify the surfaced message names the provider and its reset time."""
    message = usage_limit_message("Codex", "usage limit reached, resets at 15:00")
    assert message == "Codex usage limit reached — resets 15:00"
    assert usage_limit_message("Codex", "usage limit reached") == "Codex usage limit reached"


def test_claude_run_reports_usage_limit(tmp_path):
    """Verify a Claude Code rate-limit exit is typed as USAGE_LIMIT with a clear message."""
    driver = ClaudeCodeDriver(tmp_path)
    spec, request = _spec_request()
    response = driver.build_response(
        spec, request, [], returncode=1,
        stderr_tail="Error: Claude usage limit reached. Your limit resets at 3:00pm.",
    )
    assert response.status is ProviderRunStatus.FAILED
    assert response.error_kind is ProviderErrorKind.USAGE_LIMIT
    assert "Claude Code usage limit reached" in response.error_message
    assert "3:00pm" in response.error_message


def test_codex_run_reports_usage_limit(tmp_path):
    """Verify a Codex rate-limit exit is typed as USAGE_LIMIT with a clear message."""
    driver = CodexCliDriver(tmp_path)
    spec, request = _spec_request()
    response = driver.build_response(
        spec, request, [], returncode=1,
        stderr_tail="429 Too Many Requests: rate limit; try again in 5 minutes",
    )
    assert response.error_kind is ProviderErrorKind.USAGE_LIMIT
    assert "Codex usage limit reached" in response.error_message
    assert "5 minutes" in response.error_message


def test_non_limit_error_is_not_usage_limit(tmp_path):
    """Verify an ordinary failure stays provider_unavailable, not usage_limit."""
    driver = ClaudeCodeDriver(tmp_path)
    spec, request = _spec_request()
    response = driver.build_response(
        spec, request, [], returncode=1, stderr_tail="connection refused",
    )
    assert response.error_kind is ProviderErrorKind.PROVIDER_UNAVAILABLE


def test_usage_limit_pauses_with_a_clear_actionable_reason():
    """Verify a usage-limit failure pauses for the user with reset + /resume guidance."""
    plan = compile_single_writer_plan(session_id="s", contract_id="c")
    review_step = next(step for step in plan.steps if step.step_type is LoopStepType.REVIEW)
    result = HarnessRunResult(
        spec_id="x",
        status=HarnessStatus.FAILED,
        role=RoleName.QA,
        step_type=LoopStepType.REVIEW,
        evidence_refs=[],
        output={},
        metadata={
            "error_kind": ProviderErrorKind.USAGE_LIMIT.value,
            "error_message": "Codex usage limit reached — resets 15:00",
        },
    )

    decision = decide_runtime(review_step, result)

    assert decision.decision is LoopDecisionType.HUMAN_HANDOFF
    assert decision.stop_condition is StopCondition.HUMAN_HANDOFF_REQUESTED
    assert "usage limit reached" in decision.reason
    assert "/resume" in decision.reason
