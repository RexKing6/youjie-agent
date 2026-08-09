from pathlib import Path

from delivery_guard.data import load_incident
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.mendeley import FILE_SHA256, build_public_scenario, file_sha256
from delivery_guard.workflow import RecoveryWorkflow


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb"
CASE = ROOT / "data/cases/mendeley_drill"


def test_verified_public_rows_are_used_and_quantity_is_conserved():
    assert file_sha256(RAW) == FILE_SHA256
    scenario, lineage = build_public_scenario(RAW)
    assert len(scenario.orders) == 3
    assert sum(order.quantity for order in scenario.orders) == 217
    assert lineage["integrity"]["selected_demand_rows"] == 217
    assert lineage["integrity"]["selected_demand_sum"] == 217
    assert lineage["integrity"]["aggregate_order_sum"] == 217
    assert all(row["sheet"] == "demands" and row["row"] >= 2 for rows in lineage["public_rows"]["demands"].values() for row in rows)
    assert scenario.provenance.sources[0].license == "CC BY 4.0"
    assert scenario.provenance.sources[1].source_type == "synthetic_competition_overlay"


def test_public_case_has_three_materially_different_verified_recovery_profiles():
    scenario, _ = build_public_scenario(RAW)
    workflow = RecoveryWorkflow(scenario, load_incident(CASE / "incident.json"))
    impact = workflow.analyze()
    workflow.solve()
    assert impact.affected_orders == ["ord_public_cfg_1", "ord_public_cfg_2", "ord_public_cfg_3"]
    actual = {
        plan.profile: (
            summarize_plan(workflow.adjusted_scenario, plan)["first_due_on_time_units"],
            summarize_plan(workflow.adjusted_scenario, plan)["recovery_cost"],
        )
        for plan in workflow.verified_plans()
    }
    assert actual == {
        "service_first": (91, 728),
        "balanced": (45, 360),
        "stability_first": (0, 0),
    }
