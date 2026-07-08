"""Verify core models are split by domain with schema facade compatibility."""

from agentctl.core.models.base import AgentctlModel, CuratorModel
from agentctl.core.models.harness import HarnessRunSpec, PMPlanOutput
from agentctl.core.models.goals import GoalContract, GoalCriterion
from agentctl.core.models.init import InitProposal
from agentctl.core.models.loops import CompiledLoopPlan, LoopRunRecord
from agentctl.core.models.paths import AgentctlPaths, CuratorPaths
from agentctl.core.models.roles import RoleCollaborator, RoleContract, RoleHandoffRule
from agentctl.core.models.session import EventRecord, SessionRecord, TaskRecord
from agentctl.core.models.snapshot import WorkflowSnapshot
from agentctl.core.schema import (
    AgentctlModel as FacadeAgentctlModel,
    AgentctlPaths as FacadeAgentctlPaths,
    CuratorPaths as FacadeCuratorPaths,
    CuratorModel as FacadeCuratorModel,
    CompiledLoopPlan as FacadeCompiledLoopPlan,
    EventRecord as FacadeEventRecord,
    GoalContract as FacadeGoalContract,
    GoalCriterion as FacadeGoalCriterion,
    HarnessRunSpec as FacadeHarnessRunSpec,
    InitProposal as FacadeInitProposal,
    LoopRunRecord as FacadeLoopRunRecord,
    PMPlanOutput as FacadePMPlanOutput,
    RoleContract as FacadeRoleContract,
    RoleCollaborator as FacadeRoleCollaborator,
    RoleHandoffRule as FacadeRoleHandoffRule,
    SessionRecord as FacadeSessionRecord,
    TaskRecord as FacadeTaskRecord,
    WorkflowSnapshot as FacadeWorkflowSnapshot,
)


def test_core_model_domains_are_importable_from_focused_modules():
    """Verify focused model modules expose the expected domain classes."""
    assert CuratorModel.__name__ == "CuratorModel"
    assert AgentctlModel is CuratorModel
    assert CuratorPaths.__name__ == "CuratorPaths"
    assert AgentctlPaths is CuratorPaths
    assert InitProposal.__name__ == "InitProposal"
    assert SessionRecord.__name__ == "SessionRecord"
    assert TaskRecord.__name__ == "TaskRecord"
    assert EventRecord.__name__ == "EventRecord"
    assert GoalContract.__name__ == "GoalContract"
    assert GoalCriterion.__name__ == "GoalCriterion"
    assert RoleContract.__name__ == "RoleContract"
    assert RoleCollaborator.__name__ == "RoleCollaborator"
    assert RoleHandoffRule.__name__ == "RoleHandoffRule"
    assert CompiledLoopPlan.__name__ == "CompiledLoopPlan"
    assert LoopRunRecord.__name__ == "LoopRunRecord"
    assert HarnessRunSpec.__name__ == "HarnessRunSpec"
    assert PMPlanOutput.__name__ == "PMPlanOutput"
    assert WorkflowSnapshot.__name__ == "WorkflowSnapshot"


def test_core_schema_reexports_focused_model_classes():
    """Verify the legacy schema facade points at focused model classes."""
    assert FacadeCuratorModel is CuratorModel
    assert FacadeAgentctlModel is CuratorModel
    assert FacadeAgentctlPaths is AgentctlPaths
    assert FacadeCuratorPaths is CuratorPaths
    assert FacadeInitProposal is InitProposal
    assert FacadeSessionRecord is SessionRecord
    assert FacadeTaskRecord is TaskRecord
    assert FacadeEventRecord is EventRecord
    assert FacadeGoalContract is GoalContract
    assert FacadeGoalCriterion is GoalCriterion
    assert FacadeRoleContract is RoleContract
    assert FacadeRoleCollaborator is RoleCollaborator
    assert FacadeRoleHandoffRule is RoleHandoffRule
    assert FacadeCompiledLoopPlan is CompiledLoopPlan
    assert FacadeLoopRunRecord is LoopRunRecord
    assert FacadeHarnessRunSpec is HarnessRunSpec
    assert FacadePMPlanOutput is PMPlanOutput
    assert FacadeWorkflowSnapshot is WorkflowSnapshot


def test_domain_models_inherit_from_curator_base_model():
    """Verify domain models use the Curator base model name."""
    for model in (
        CuratorPaths,
        InitProposal,
        SessionRecord,
        TaskRecord,
        EventRecord,
        GoalContract,
        GoalCriterion,
        RoleCollaborator,
        RoleContract,
        RoleHandoffRule,
        CompiledLoopPlan,
        LoopRunRecord,
        HarnessRunSpec,
        PMPlanOutput,
        WorkflowSnapshot,
    ):
        assert issubclass(model, CuratorModel)
