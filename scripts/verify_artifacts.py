"""Fail closed if generated demo or adversarial artifacts violate traceability."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DELIVERABLES = (
    "README.md",
    "LICENSE",
    "docs/architecture.md",
    "docs/data_provenance.md",
    "docs/research_gap_matrix.md",
    "docs/adversarial_validation.md",
    "docs/submission.md",
    "docs/demo_script.md",
    "docs/defense_qa.md",
    "docs/judging_rubric.md",
    "docs/agent_evaluation.md",
    "docs/youjie_goai_pitch.pptx",
    "docs/youjie_demo.mp4",
    "artifacts/demo_screenshot.jpg",
    "artifacts/agent_demo_run.json",
    "artifacts/agent_eval_report.json",
    "artifacts/agent_eval_report.md",
    "artifacts/infeasible_diagnostic.json",
    "artifacts/public_data_graph_run.json",
    "artifacts/chaos_drill_run.json",
    "artifacts/delivery_guard_submission.zip",
)


def load(name: str) -> dict:
    path = ROOT / "artifacts" / name
    if not path.exists():
        raise SystemExit(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    missing = [name for name in REQUIRED_DELIVERABLES if not (ROOT / name).is_file()]
    assert not missing, f"missing deliverables: {missing}"
    empty = [name for name in REQUIRED_DELIVERABLES if (ROOT / name).stat().st_size == 0]
    assert not empty, f"empty deliverables: {empty}"

    demo = load("demo_run.json")
    adversarial = load("adversarial_report.json")
    agent_demo = load("agent_demo_run.json")
    agent_eval = load("agent_eval_report.json")
    diagnostic = load("infeasible_diagnostic.json")
    public_graph = load("public_data_graph_run.json")
    chaos_drill = load("chaos_drill_run.json")
    lineage = json.loads(
        (ROOT / "data/cases/mendeley_drill/lineage.json").read_text(encoding="utf-8")
    )

    assert demo["state"] == "orders_generated"
    assert demo["approval"] and demo["approval"]["decision"] == "approve"
    assert demo["work_orders"]
    assert all(order["execution_status"] == "draft_only" for order in demo["work_orders"])
    assert all(order["scenario_hash"] == demo["scenario_hash"] for order in demo["work_orders"])
    assert all(
        order["approval_id"] == demo["approval"]["approval_id"]
        for order in demo["work_orders"]
    )
    approved_plan = next(
        plan for plan in demo["plans"] if plan["plan_id"] == demo["approval"]["plan_id"]
    )
    assert approved_plan["evidence"]["verified"] is True
    assert approved_plan["evidence"]["violations"] == []

    assert adversarial["failed_cases"] == 0
    assert adversarial["invariant_violations"] == []
    assert adversarial["passed_cases"] == adversarial["total_cases"]
    assert agent_demo["context"]["model_mode"] == "replay"
    assert agent_demo["context"]["state"] == "completed"
    assert len(agent_demo["context"]["tool_traces"]) >= 8
    assert agent_demo["context"]["retrieved_evidence"]
    assert all(
        item["source_ref"] and item["document_hash"]
        for item in agent_demo["context"]["retrieved_evidence"]
    )
    expected = {
        "service_first": (100, 0, 1040, 80, 20),
        "balanced": (90, 10, 580, 60, 10),
        "stability_first": (60, 40, 0, 0, 0),
    }
    for profile, values in expected.items():
        summary = agent_demo["plan_summaries"][profile]
        assert (
            summary["first_due_on_time_units"],
            summary["first_due_late_units"],
            summary["recovery_cost"],
            summary["alternate_supplier_units"],
            summary["overtime_units"],
        ) == values
    assert all(
        plan["evidence"]["verified"] and not plan["evidence"]["violations"]
        for plan in agent_demo["workflow"]["plans"]
    )
    assert agent_eval["total_cases"] == 30
    assert agent_eval["passed_cases"] == 30
    assert agent_eval["failed_cases"] == 0
    assert agent_eval["repeat_outputs_identical"] is True
    assert agent_eval["metrics"]["forbidden_tool_execution_count"] == 0
    assert "not a live-model accuracy claim" in agent_eval["claim_boundary"]
    assert diagnostic["feasible_by_due"] is False
    assert diagnostic["maximum_deliverable_by_due"] == 100
    assert diagnostic["maximum_deliverable_within_horizon"] == 140
    assert diagnostic["earliest_full_delivery_hour"] is None
    assert len(diagnostic["alternatives"]) >= 2
    assert lineage["integrity"]["selected_demand_rows"] == 217
    assert lineage["integrity"]["selected_demand_sum"] == 217
    assert lineage["integrity"]["aggregate_order_sum"] == 217
    assert public_graph["status"] == "completed"
    assert public_graph["run_metadata"]["orchestrator"] == "LangGraph"
    assert public_graph["run_metadata"]["human_interrupt_observed"] is True
    assert public_graph["work_orders"]
    assert all(item["execution_status"] == "draft_only" for item in public_graph["work_orders"])
    assert {item["node"] for item in public_graph["graph_trace"]} >= {
        "understand_incident", "plan_investigation", "execute_investigation",
        "analyze_and_solve", "human_approval", "draft_actions",
    }
    assert chaos_drill["drill"]["incident"]["source_type"] == "synthetic_chaos_drill"
    assert chaos_drill["run_metadata"]["generator"] == "ChaosDrillAgent"
    assert chaos_drill["run_metadata"]["human_interrupt_observed"] is True
    print(
        f"verified demo={len(demo['work_orders'])} drafts, "
        f"adversarial={adversarial['passed_cases']}/{adversarial['total_cases']}, "
        f"agent_eval={agent_eval['passed_cases']}/{agent_eval['total_cases']}, "
        f"deliverables={len(REQUIRED_DELIVERABLES)}"
    )


if __name__ == "__main__":
    main()
