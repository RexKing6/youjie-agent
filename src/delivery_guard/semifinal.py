"""Frozen semifinal showcase cases outside the Streamlit presentation layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from delivery_guard.diagnostics import diagnose_product_request
from delivery_guard.models import Scenario


def load_semifinal_cases(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {item["case_id"]: item for item in payload["cases"]}


def run_infeasible_case(scenario: Scenario, case: dict[str, Any]) -> dict[str, Any]:
    diagnostic = diagnose_product_request(
        scenario,
        product_id=case["product_id"],
        requested_total_units=case["requested_total_units"],
        due_hour=case["due_hour"],
    )
    if diagnostic["feasible_within_horizon"]:
        raise ValueError("frozen infeasible case no longer proves infeasibility")
    return {
        "status": "infeasible",
        "case_id": case["case_id"],
        "diagnostic": diagnostic,
        "work_orders": [],
        "graph_trace": [
            {"node": "understand_request", "summary": "Parsed the requested commitment and due hour."},
            {"node": "query_factory_snapshot", "summary": "Loaded hashable material and capacity evidence."},
            {"node": "diagnose_upper_bound", "summary": "Computed deterministic material and line-capacity upper bounds."},
            {"node": "stop_unsafe_commitment", "summary": "Stopped before solve/approval because the request exceeds the proven horizon bound."},
        ],
        "tool_traces": [
            {
                "sequence": 1,
                "tool_name": "diagnose_product_request",
                "input_summary": {
                    "product_id": case["product_id"],
                    "requested_total_units": case["requested_total_units"],
                    "due_hour": case["due_hour"],
                },
                "result_summary": {
                    "maximum_deliverable_by_due": diagnostic["maximum_deliverable_by_due"],
                    "maximum_deliverable_within_horizon": diagnostic["maximum_deliverable_within_horizon"],
                    "shortfall_by_due": diagnostic["due_bound"]["shortfall_units"],
                },
                "success": True,
                "source_refs": ["data/cases/mendeley_drill/scenario.json"],
            }
        ],
    }
