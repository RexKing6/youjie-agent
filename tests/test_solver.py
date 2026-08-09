from delivery_guard.data import apply_incident, load_incident, scenario_incident_hash
from delivery_guard.solver import solve_profiles
from delivery_guard.verifier import verify_plan


def test_supplier_delay_has_verified_recovery(solved_workflow):
    verified = solved_workflow.verified_plans()
    assert len(verified) == 3
    assert all(plan.evidence.verified for plan in verified)
    assert all(not plan.evidence.violations for plan in verified)
    assert all(plan.purchases for plan in verified)


def test_independent_verifier_rejects_wrong_line(solved_workflow):
    plan = solved_workflow.verified_plans()[0].model_copy(deep=True)
    smt_task = next(task for task in plan.scheduled_operations if "_smt" in task.operation_id)
    smt_task.line_id = "line_assembly"
    violations = verify_plan(solved_workflow.adjusted_scenario, plan)
    assert any("not eligible" in violation for violation in violations)


def test_impossible_critical_order_has_no_verified_plan(scenario):
    incident = load_incident("data/incidents/impossible_critical_order.json")
    adjusted = apply_incident(scenario, incident)
    plans = solve_profiles(adjusted, scenario_incident_hash(scenario, incident))
    assert not [plan for plan in plans if plan.evidence.verified]
    assert all(plan.evidence.solver_status in {"INFEASIBLE", "UNKNOWN"} for plan in plans)
