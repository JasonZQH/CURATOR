"""Define constrained status and type values for Curator state."""

from enum import Enum


class SessionMode(str, Enum):
    """Constrain how much autonomy a session may use."""

    PLAN_FIRST = "plan-first"
    AUTO = "auto"


class TaskStatus(str, Enum):
    """Constrain the scheduler-visible lifecycle of a task."""

    QUEUED = "queued"
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RoleName(str, Enum):
    """Constrain the Phase 0 team role names."""

    PM = "pm"
    ENGINEER = "engineer"
    QA = "qa"


class ProviderName(str, Enum):
    """Constrain provider identifiers that can execute role work."""

    CODEX = "codex"
    CLAUDE_CODE = "claude-code"


class ProviderRunStatus(str, Enum):
    """Constrain provider run ledger outcomes."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderProfileStatus(str, Enum):
    """Constrain configured provider profile availability."""

    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class ProviderBindingStatus(str, Enum):
    """Constrain role-to-provider binding lifecycle states."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class ProviderSessionStatus(str, Enum):
    """Constrain provider session lifecycle states."""

    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class QuotaStatus(str, Enum):
    """Constrain observed provider quota states."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    LIMITED = "limited"
    EXHAUSTED = "exhausted"


class ProviderErrorKind(str, Enum):
    """Constrain typed provider failure categories."""

    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PERMISSION_DENIED = "permission_denied"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class PauseStatus(str, Enum):
    """Constrain durable pause record states."""

    OPEN = "open"
    RESOLVED = "resolved"


class DiscoveryStatus(str, Enum):
    """Constrain pre-goal discovery discussion states."""

    ACTIVE = "active"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


class ActionType(str, Enum):
    """Constrain action policy request types."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    SHELL_COMMAND = "shell_command"
    VCS_REMOTE_WRITE = "vcs_remote_write"


class RoleInstanceStatus(str, Enum):
    """Constrain pool worker lifecycle states."""

    IDLE = "idle"
    BUSY = "busy"
    PAUSED = "paused"
    BLOCKED = "blocked"


class WorkItemKind(str, Enum):
    """Constrain queueable work item categories."""

    DISCOVERY = "discovery"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    RESEARCH = "research"


class WorkItemStatus(str, Enum):
    """Constrain queueable work item lifecycle states."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AssignmentStatus(str, Enum):
    """Constrain worker assignment lifecycle states."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ApprovalKind(str, Enum):
    """Constrain user approval request categories."""

    GOAL = "goal"
    PLAN = "plan"
    SCOPE_CHANGE = "scope_change"
    PERMISSION = "permission"
    DESTRUCTIVE_ACTION = "destructive_action"
    EXTERNAL_WRITE = "external_write"


class ApprovalStatus(str, Enum):
    """Constrain user approval lifecycle states."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MessageType(str, Enum):
    """Constrain routed message categories between roles."""

    PLAN_READY = "plan_ready"
    IMPLEMENTATION_COMPLETE = "implementation_complete"
    VALIDATION_COMPLETE = "validation_complete"


class EventType(str, Enum):
    """Constrain durable event categories emitted by Curator."""

    SESSION_CREATED = "session_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    MESSAGE_CREATED = "message_created"
    PROVIDER_RUN_STARTED = "provider_run_started"
    PROVIDER_TOOL_CALL = "provider_tool_call"
    PROVIDER_PERMISSION_REQUEST = "provider_permission_request"
    PROVIDER_RUN_COMPLETED = "provider_run_completed"


class LoopStatus(str, Enum):
    """Constrain the lifecycle of a loop run instance."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class GoalStatus(str, Enum):
    """Constrain the lifecycle of a user-accepted goal."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


class LoopStepType(str, Enum):
    """Constrain the ordered step types used by loop templates."""

    PLAN = "plan"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    REVIEW = "review"
    CONFIRM = "confirm"


class StepExecutorType(str, Enum):
    """Constrain how a compiled loop step is executed."""

    PROVIDER = "provider"
    VERIFIER = "verifier"
    HUMAN_GATE = "human_gate"


class LoopDecisionType(str, Enum):
    """Constrain deterministic scheduler decisions after loop iterations.

    CONTINUE_TO_* members are deprecated ledger-only values kept so older
    databases still deserialize; new plans advance by queue position and use
    CONTINUE, RETRY_STEP, HUMAN_HANDOFF, STOP_DONE, or STOP_FAILED.
    """

    CONTINUE = "continue"
    RETRY_STEP = "retry_step"
    CONTINUE_TO_ENGINEER = "continue_to_engineer"
    CONTINUE_TO_QA = "continue_to_qa"
    CONTINUE_TO_PM = "continue_to_pm"
    RETRY_IMPLEMENTATION = "retry_implementation"
    RETRY_VALIDATION = "retry_validation"
    HUMAN_HANDOFF = "human_handoff"
    STOP_DONE = "stop_done"
    STOP_FAILED = "stop_failed"


class StopCondition(str, Enum):
    """Constrain the reasons a loop may stop."""

    DONE_CRITERIA_MET = "done_criteria_met"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    VALIDATION_FAILED = "validation_failed"
    PROVIDER_FAILED = "provider_failed"
    HUMAN_HANDOFF_REQUESTED = "human_handoff_requested"
    CONTRACT_VIOLATION = "contract_violation"


class EvidenceKind(str, Enum):
    """Constrain evidence categories stored in the loop ledger."""

    PLAN = "plan"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    REVIEW = "review"
    PM_CONFIRMATION = "pm_confirmation"
    ARTIFACT = "artifact"
    LOG = "log"


class HarnessStatus(str, Enum):
    """Constrain execution outcomes reported by the harness."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
