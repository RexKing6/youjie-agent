from pathlib import Path

from delivery_guard.data import load_incident, load_scenario
from delivery_guard.diagnostics import diagnose_product_request
from delivery_guard.workflow import RecoveryWorkflow


ROOT = Path(__file__).resolve().parents[1]


def test_impossible_request_returns_numeric_bounds_and_alternatives() -> None:
    case_dir = ROOT / "data/cases/delivery_crisis"
    workflow = RecoveryWorkflow(
        load_scenario(case_dir / "scenario.json"),
        load_incident(case_dir / "incident.json"),
    )
    workflow.analyze()
    result = diagnose_product_request(
        workflow.adjusted_scenario,
        product_id="prd_sensor_node",
        requested_total_units=240,
        due_hour=112,
    )

    assert result["feasible_by_due"] is False
    assert result["feasible_within_horizon"] is False
    assert result["maximum_deliverable_by_due"] == 100
    assert result["maximum_deliverable_within_horizon"] == 140
    assert result["earliest_full_delivery_hour"] is None
    assert result["minimum_additional_capacity_units"] == 20
    shortages = {item["item_id"]: item["shortfall"] for item in result["minimum_additional_material"]}
    assert shortages == {"mat_case": 100, "mat_mcu": 120, "mat_pcb": 100}
    assert len(result["alternatives"]) == 3
