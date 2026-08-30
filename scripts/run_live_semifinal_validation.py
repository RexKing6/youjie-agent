"""Run the frozen semifinal showcase cases through the configured live model."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from delivery_guard.data import load_scenario
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.semifinal import load_semifinal_cases, run_infeasible_case

from run_live_model_evaluation import ROOT, configured_model


CASE = ROOT / "data/cases/mendeley_drill"


def graph(model) -> DeliveryGuardGraph:
    return DeliveryGuardGraph(
        scenario_path=CASE / "scenario.json",
        knowledge_paths=[
            CASE / "customer_sla.md",
            CASE / "procurement_policy.md",
            CASE / "safety_policy.md",
        ],
        model=model,
    )


def case_text(case: dict) -> str:
    if case["case_id"] == "source_conflict":
        refs = [
            CASE / "evidence/supplier_email.eml",
            CASE / "evidence/carrier_notice_source.txt",
            CASE / "evidence/mes_snapshot.csv",
        ]
        return "\n\n--- NEXT SOURCE ---\n\n".join(
            path.read_text(encoding="utf-8") for path in refs
        )
    return (ROOT / case["input_ref"]).read_text(encoding="utf-8")


def compact_graph_result(case: dict, result: dict, elapsed: float) -> dict:
    draft = result.get("incident_draft", {})
    security_flags = draft.get("security_flags", [])
    passed = result.get("status") == case["expected_stop"]
    if case["case_id"] == "prompt_injection":
        passed = passed and "prompt_injection" in security_flags
    return {
        "case_id": case["case_id"],
        "expected_stop": case["expected_stop"],
        "actual_stop": result.get("status"),
        "passed": passed,
        "latency_seconds": round(elapsed, 3),
        "model_mode": result.get("model_mode"),
        "model_name": result.get("model_name"),
        "incident_draft": draft,
        "graph_nodes": [item["node"] for item in result.get("graph_trace", [])],
        "verified_plan_count": sum(
            plan.get("evidence", {}).get("verified", False)
            for plan in result.get("plans", [])
        ),
        "work_order_count_before_approval": len(result.get("work_orders", [])),
    }


def main() -> None:
    model = configured_model()
    cases = load_semifinal_cases(CASE / "semifinal_cases.json")
    scenario = load_scenario(CASE / "scenario.json")
    results = []
    for case in cases.values():
        started = time.perf_counter()
        if case["case_id"] == "infeasible_request":
            diagnostic = run_infeasible_case(scenario, case)
            details = diagnostic["diagnostic"]
            results.append({
                "case_id": case["case_id"],
                "expected_stop": case["expected_stop"],
                "actual_stop": diagnostic["status"],
                "passed": diagnostic["status"] == case["expected_stop"],
                "latency_seconds": round(time.perf_counter() - started, 3),
                "model_mode": "deterministic_diagnostic",
                "requested_total_units": details["requested_total_units"],
                "maximum_deliverable_by_due": details["maximum_deliverable_by_due"],
                "shortfall_units": details["due_bound"]["shortfall_units"],
                "work_order_count": len(diagnostic.get("work_orders", [])),
            })
            continue
        try:
            preflight_conflicts = []
            preflight_confirmations = []
            if case["case_id"] == "source_conflict":
                from delivery_guard.evidence import load_evidence_bundle

                bundle = load_evidence_bundle(ROOT / case["evidence_manifest"])
                preflight_conflicts = [
                    f"{item['field_name']}: {item['reason']}"
                    for item in bundle["conflicts"]
                ]
                preflight_confirmations = ["authoritative_delay_hours"]
            result = graph(model).start(
                raw_text=case_text(case),
                source_ref=case["input_ref"],
                replay_key="unused_in_live_mode",
                thread_id="live-semifinal-" + uuid4().hex,
                preflight_conflicts=preflight_conflicts,
                preflight_required_confirmations=preflight_confirmations,
            )
            results.append(compact_graph_result(case, result, time.perf_counter() - started))
        except Exception as exc:
            results.append({
                "case_id": case["case_id"],
                "expected_stop": case["expected_stop"],
                "actual_stop": "error",
                "passed": False,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "error_class": type(exc).__name__,
            })
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "live_plus_deterministic",
        "model_name": model.model_name,
        "total_cases": len(results),
        "passed_cases": sum(item["passed"] for item in results),
        "failed_cases": sum(not item["passed"] for item in results),
        "results": results,
        "secret_handling": {
            "source": ".streamlit/secrets.toml (gitignored)",
            "api_key_in_report": False,
            "endpoint_in_report": False,
        },
        "claim_boundary": (
            "Synthetic semifinal fixtures plus public-derived scenario. Live language understanding "
            "is model-specific; feasibility and work-order gates remain deterministic."
        ),
    }
    output = ROOT / "artifacts/live_semifinal_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "model": report["model_name"],
        "passed": report["passed_cases"],
        "total": report["total_cases"],
        "cases": [
            {"case_id": item["case_id"], "passed": item["passed"], "stop": item["actual_stop"]}
            for item in results
        ],
        "output": str(output),
        "api_key_logged": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
