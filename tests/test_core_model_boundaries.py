"""Verify core models are split by domain with schema facade compatibility."""

from curator.core.models.base import CuratorModel
from curator.core.models.harness import HarnessRunSpec, PMPlanOutput
from curator.core.models.goals import GoalContract, GoalCriterion
from curator.core.models.init import InitProposal
from curator.core.models.loops import CompiledLoopPlan, LoopRunRecord
from curator.core.models.paths import CuratorPaths
from curator.core.models.roles import RoleCollaborator, RoleContract, RoleHandoffRule
from curator.core.models.session import EventRecord, SessionRecord, TaskRecord
from curator.core.models.snapshot import WorkflowSnapshot
from curator.core.schema import (
    CuratorModel as FacadeCuratorModel,
    CuratorPaths as FacadeCuratorPaths,
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
    assert CuratorPaths.__name__ == "CuratorPaths"
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
