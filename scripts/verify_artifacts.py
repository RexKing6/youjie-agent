"""Fail closed if generated demo or adversarial artifacts violate traceability."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile


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
    "docs/semifinal_integration_spec.md",
    "docs/semifinal_feedback_verification.md",
    "docs/defense_evidence_index.md",
    "docs/defense_runbook.md",
    "contracts/openapi.yaml",
    "contracts/asyncapi.yaml",
    "contracts/mappings/profile_mapping.md",
    "contracts/schemas/canonical_command.schema.json",
    "contracts/schemas/transport_ack.schema.json",
    "contracts/schemas/execution_callback.schema.json",
    "contracts/schemas/callback_receipt.schema.json",
    "contracts/examples/sap_s4_dm_contract_profile.example.json",
    "contracts/examples/kingdee_blacklake_contract_profile.example.json",
    "docs/youjie_goai_semifinal_pitch_8slides.pptx",
    "docs/youjie_goai_semifinal_pitch_8slides.pdf",
    "docs/youjie_semifinal_demo.mp4",
    "docs/youjie_semifinal_demo.zh-CN.srt",
    "artifacts/demo_screenshot.jpg",
    "artifacts/agent_demo_run.json",
    "artifacts/agent_eval_report.json",
    "artifacts/agent_eval_report.md",
    "artifacts/infeasible_diagnostic.json",
    "artifacts/public_data_graph_run.json",
    "artifacts/chaos_drill_run.json",
    "artifacts/semifinal_comparison_report.json",
    "artifacts/semifinal_comparison_report.md",
    "artifacts/live_agent_eval_report.json",
    "artifacts/live_agent_eval_report.md",
    "artifacts/live_semifinal_report.json",
    "artifacts/integration_validation_report.json",
    "artifacts/erpnext_real_validation.json",
    "artifacts/openmes_real_validation.json",
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
    comparison = load("semifinal_comparison_report.json")
    live_eval = load("live_agent_eval_report.json")
    live_semifinal = load("live_semifinal_report.json")
    integration = load("integration_validation_report.json")
    erpnext_real = load("erpnext_real_validation.json")
    openmes_real = load("openmes_real_validation.json")
    evidence_manifest = json.loads(
        (ROOT / "data/cases/mendeley_drill/evidence/manifest.json").read_text(
            encoding="utf-8"
        )
    )
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
    assert set(comparison["systems"]) == {
        "plain_chat_reference", "fixed_workflow_reference", "youjie_bounded_agent"
    }
    assert comparison["systems"]["youjie_bounded_agent"]["passed_cases"] == 12
    assert comparison["systems"]["plain_chat_reference"]["passed_cases"] < 12
    assert comparison["systems"]["fixed_workflow_reference"]["passed_cases"] < 12
    assert all(
        item["repeat_outputs_identical"]
        for item in comparison["systems"].values()
    )
    assert live_eval["evaluation_mode"] == "live"
    assert live_eval["model_name"] == "qwen3.8-max"
    assert live_eval["run_count"] == 3
    assert live_eval["total_model_calls"] == 90
    assert min(live_eval["all_run_pass_counts"]) >= 29
    assert live_eval["all_run_forbidden_tool_counts"] == [0, 0, 0]
    assert live_eval["secret_handling"]["api_key_in_report"] is False
    assert live_semifinal["passed_cases"] == live_semifinal["total_cases"] == 4
    assert integration["failed_checks"] == 0
    assert integration["passed_checks"] == integration["total_checks"]
    assert integration["total_checks"] >= 36
    assert integration["repeat_runs_per_profile"] == 10
    assert set(integration["profiles"]) == {
        "sap_s4_dm_contract_profile",
        "kingdee_blacklake_contract_profile",
        "erpnext_open_source_test_profile",
        "openmes_open_source_test_profile",
    }
    for profile in integration["profiles"].values():
        assert profile["repeat_outputs_identical"] is True
        run = profile["representative_run"]
        assert run["overall_business_status"] == "PARTIALLY_APPLIED"
        assert run["plan_stale"] is True
        assert run["old_approval_reused"] is False
        assert run["replan"]["status"] == "awaiting_approval"
        assert run["replan"]["work_orders"] == []
        assert run["safety"]["device_control"] is False
    assert erpnext_real["schema_version"] == "youjie.erpnext_real_validation/v1"
    assert erpnext_real["runtime"]["status"] == "connected"
    assert erpnext_real["runtime"]["environment"] == "test"
    assert erpnext_real["runtime"]["credentials_exposed"] is False
    assert erpnext_real["boundaries"]["standalone_mes_claim"] is False
    assert len(erpnext_real["records"]) == 4
    assert len(erpnext_real["referenced_commitments"]) == 1
    assert erpnext_real["referenced_commitments"][0]["committed"] is True
    assert {record["doctype"] for record in erpnext_real["records"]} == {
        "Material Request", "Work Order"
    }
    assert all(record["docstatus"] == 0 for record in erpnext_real["records"])
    assert all(erpnext_real["assertions"].values())
    assert openmes_real["schema_version"] == "youjie.openmes_real_validation/v1"
    assert openmes_real["runtime"]["status"] == "connected"
    assert openmes_real["runtime"]["environment"] == "test"
    assert len(openmes_real["runtime"]["upstream_commit"]) == 40
    assert openmes_real["runtime"]["credentials_exposed"] is False
    assert len(openmes_real["erpnext"]["work_orders"]) == 3
    assert len(openmes_real["openmes"]["records"]) == 3
    assert {
        item["erpnext_work_order"] for item in openmes_real["erpnext"]["work_orders"]
    } == {
        item["order_no"] for item in openmes_real["openmes"]["records"]
    }
    assert openmes_real["openmes"]["duplicate_retry_created_nothing"] is True
    assert openmes_real["feedback_validation"]["status"] == (
        "change_detected_and_old_approval_invalidated"
    )
    assert openmes_real["feedback_validation"]["delta"]["changed"] is True
    assert openmes_real["feedback_validation"]["delta"]["invalidates_approval"] is True
    assert openmes_real["feedback_validation"]["previous_approval_valid"] is False
    assert openmes_real["feedback_validation"]["new_commands_blocked"] is True
    assert openmes_real["boundaries"]["device_control"] is False
    assert openmes_real["boundaries"]["production_tenant"] is False
    assert openmes_real["boundaries"]["physical_execution_claim"] is False
    assert all(openmes_real["assertions"].values())
    for schema_name in (
        "canonical_command", "transport_ack", "execution_callback", "callback_receipt"
    ):
        schema = json.loads(
            (ROOT / f"contracts/schemas/{schema_name}.schema.json").read_text(encoding="utf-8")
        )
        assert schema["type"] == "object"
    assert len(evidence_manifest["records"]) == 3
    assert {item["media_type"] for item in evidence_manifest["records"]} == {
        "image/png", "application/pdf", "text/csv"
    }
    with ZipFile(ROOT / "artifacts/youjie_semifinal_submission.zip") as archive:
        packaged = set(archive.namelist())
    assert not any(".streamlit/" in name for name in packaged)
    assert not any(
        name.endswith(("secrets.toml", ".env", "erpnext_credentials.json"))
        for name in packaged
    )
    assert "goai_delivery_guard/artifacts/live_agent_eval_report.json" in packaged
    assert "goai_delivery_guard/artifacts/integration_validation_report.json" in packaged
    assert "goai_delivery_guard/artifacts/erpnext_real_validation.json" in packaged
    assert "goai_delivery_guard/artifacts/openmes_real_validation.json" in packaged
    assert "goai_delivery_guard/contracts/openapi.yaml" in packaged
    assert "goai_delivery_guard/src/delivery_guard/integration/orchestrator.py" in packaged
    assert "goai_delivery_guard/docs/youjie_semifinal_demo.mp4" in packaged
    assert "goai_delivery_guard/docs/youjie_goai_semifinal_pitch_8slides.pptx" in packaged
    assert "goai_delivery_guard/docs/youjie_goai_semifinal_pitch_8slides.pdf" in packaged
    assert "goai_delivery_guard/docs/youjie_semifinal_demo.zh-CN.srt" in packaged
    assert "goai_delivery_guard/frontend/site/app/page.tsx" in packaged
    assert "goai_delivery_guard/frontend/site/components/live-agent-workbench.tsx" in packaged
    print(
        f"verified demo={len(demo['work_orders'])} drafts, "
        f"adversarial={adversarial['passed_cases']}/{adversarial['total_cases']}, "
        f"agent_eval={agent_eval['passed_cases']}/{agent_eval['total_cases']}, "
        f"comparison={comparison['systems']['youjie_bounded_agent']['passed_cases']}/12, "
        f"live={live_eval['all_run_pass_counts']}, "
        f"deliverables={len(REQUIRED_DELIVERABLES)}"
    )


if __name__ == "__main__":
    main()
