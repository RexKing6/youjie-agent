from delivery_guard.data import load_incident, load_scenario
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.solver import solve_candidate
from delivery_guard.workflow import RecoveryWorkflow


def crisis_workflow():
    scenario = load_scenario("data/cases/delivery_crisis/scenario.json")
    incident = load_incident("data/cases/delivery_crisis/incident.json")
    workflow = RecoveryWorkflow(scenario, incident)
    workflow.analyze()
    workflow.solve()
    return scenario, workflow


def test_delivery_crisis_profiles_are_materially_different():
    _scenario, workflow = crisis_workflow()
    by_profile = {plan.profile: plan for plan in workflow.verified_plans()}
    assert set(by_profile) == {"service_first", "balanced", "stability_first"}

    expected = {
        "service_first": (100, 0, 1040, 80, 20),
        "balanced": (90, 10, 580, 60, 10),
        "stability_first": (60, 40, 0, 0, 0),
    }
    for profile, plan in by_profile.items():
        metrics = plan.objective_breakdown
        beta_units = sum(
            purchase.quantity
            for purchase in plan.purchases
            if purchase.source_id == "src_beta_mcu_emergency"
        )
        overtime_units = len({
            task.order_id for task in plan.scheduled_operations if task.overtime
        }) * 10
        actual = (
            metrics["first_due_on_time_units"],
            metrics["first_due_late_units"],
            metrics["recovery_cost"],
            beta_units,
            overtime_units,
        )
        assert actual == expected[profile]


def test_plan_summary_uses_grouped_customer_language_and_baseline_diff():
    scenario, workflow = crisis_workflow()
    baseline = solve_candidate(scenario, "baseline_snapshot", "service_first")
    balanced = next(plan for plan in workflow.verified_plans() if plan.profile == "balanced")
    summary = summarize_plan(workflow.adjusted_scenario, balanced, baseline)
    assert summary["groups"]["order_a"]["on_time_units"] == 40
    assert summary["groups"]["order_b"]["on_time_units"] == 50
    assert summary["groups"]["order_b"]["late_units"] == 10
    assert summary["alternate_supplier_units"] == 60
    assert summary["overtime_units"] == 10
    assert summary["schedule_changes"] > 0


def test_crisis_plan_verifier_still_guards_every_profile():
    _scenario, workflow = crisis_workflow()
    assert all(plan.evidence.verified for plan in workflow.plans)
    assert all(not plan.evidence.violations for plan in workflow.plans)
