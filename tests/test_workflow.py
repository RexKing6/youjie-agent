import pytest

from delivery_guard.hashing import candidate_plan_hash
from delivery_guard.models import WorkflowState


def balanced_plan(workflow):
    return next(plan for plan in workflow.verified_plans() if plan.profile == "balanced")


def test_work_orders_require_approval(solved_workflow):
    with pytest.raises(RuntimeError, match="approved state"):
        solved_workflow.generate_orders()


def test_approved_plan_generates_traceable_drafts(solved_workflow):
    plan = balanced_plan(solved_workflow)
    approval = solved_workflow.approve(plan.plan_id, "operator_01", "Accept balanced recovery")
    drafts = solved_workflow.generate_orders()
    assert solved_workflow.state == WorkflowState.ORDERS_GENERATED
    assert drafts
    assert all(draft.approval_id == approval.approval_id for draft in drafts)
    assert all(draft.execution_status == "draft_only" for draft in drafts)


def test_tampered_plan_invalidates_approval(solved_workflow):
    plan = balanced_plan(solved_workflow)
    solved_workflow.approve(plan.plan_id, "operator_01", "Approve before tamper")
    plan.purchases[0].quantity += 1
    with pytest.raises(ValueError, match="plan hash changed"):
        solved_workflow.generate_orders()


def test_stale_scenario_invalidates_approval(solved_workflow):
    plan = balanced_plan(solved_workflow)
    solved_workflow.approve(plan.plan_id, "operator_01", "Approve original snapshot")
    solved_workflow.scenario_hash = "changed_snapshot"
    with pytest.raises(ValueError, match="scenario hash changed"):
        solved_workflow.generate_orders()


def test_solver_evidence_hash_matches_plan(solved_workflow):
    for plan in solved_workflow.plans:
        assert plan.evidence.plan_hash == candidate_plan_hash(plan)
