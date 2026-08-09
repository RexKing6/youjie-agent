"""Adversarial scenario runner and invariant checks."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from delivery_guard.data import load_incident, load_scenario
from delivery_guard.models import Scenario
from delivery_guard.verifier import verify_plan
from delivery_guard.workflow import RecoveryWorkflow


def _mutate_scenario(raw: dict[str, Any], mutation: str) -> dict[str, Any]:
    payload = copy.deepcopy(raw)
    if mutation == "bom_cycle":
        payload["bom"].extend(
            [
                {
                    "parent_item_id": "prd_sensor_hub",
                    "component_item_id": "prd_gateway",
                    "quantity": 1,
                },
                {
                    "parent_item_id": "prd_gateway",
                    "component_item_id": "prd_sensor_hub",
                    "quantity": 1,
                },
            ]
        )
    elif mutation == "negative_inventory":
        payload["inventory"][0]["on_hand"] = -1
    elif mutation == "duplicate_order_id":
        payload["orders"].append(copy.deepcopy(payload["orders"][0]))
        payload["orders"][-1]["quantity"] += 1
    elif mutation == "dangling_bom_reference":
        payload["bom"][0]["component_item_id"] = "mat_missing"
    elif mutation == "zero_capacity_line":
        payload["production_lines"][0]["unavailable_windows"] = [
            {"start_hour": 0, "end_hour": payload["horizon_hours"]}
        ]
    else:
        raise ValueError(f"unknown mutation: {mutation}")
    return payload


def _run_workflow(scenario_path: Path, incident_path: Path) -> RecoveryWorkflow:
    workflow = RecoveryWorkflow(load_scenario(scenario_path), load_incident(incident_path))
    workflow.analyze()
    workflow.solve()
    return workflow


def evaluate_suite(
    scenario_path: str | Path,
    suite_path: str | Path,
) -> dict[str, Any]:
    scenario_path = Path(scenario_path)
    suite_path = Path(suite_path)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    raw_scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    case_results: list[dict[str, Any]] = []
    invariant_violations: list[str] = []

    for case in suite["cases"]:
        case_id = case["case_id"]
        passed = False
        detail = ""
        try:
            if case["type"] == "scenario_validation":
                try:
                    Scenario.model_validate(_mutate_scenario(raw_scenario, case["mutation"]))
                    detail = "invalid scenario was accepted"
                except (ValidationError, ValueError) as exc:
                    passed = case["expect_error_contains"].lower() in str(exc).lower()
                    detail = str(exc).splitlines()[0]

            elif case["type"] == "incident_run":
                workflow = _run_workflow(
                    scenario_path,
                    suite_path.parent / case["incident"],
                )
                verified_count = len(workflow.verified_plans())
                expected = case["expected_verified_plans"]
                if isinstance(expected, int):
                    passed = verified_count == expected
                else:
                    passed = verified_count >= expected["min"]
                detail = f"verified_plans={verified_count}"
                if passed and case.get("approve_and_generate") and verified_count:
                    chosen = next(
                        (plan for plan in workflow.verified_plans() if plan.profile == "balanced"),
                        workflow.verified_plans()[0],
                    )
                    workflow.approve(chosen.plan_id, "adversarial_operator", case_id)
                    drafts = workflow.generate_orders()
                    passed = bool(drafts) and all(
                        draft.execution_status == "draft_only" for draft in drafts
                    )
                    detail += f", drafts={len(drafts)}"

            elif case["type"] == "workflow_attack":
                workflow = _run_workflow(
                    scenario_path,
                    suite_path.parent / case["incident"],
                )
                attack = case["attack"]
                if attack == "unapproved_work_orders":
                    try:
                        workflow.generate_orders()
                        detail = "unapproved work orders were generated"
                    except RuntimeError:
                        passed = True
                        detail = "approval gate blocked generation"
                elif attack == "prompt_injection":
                    passed = (
                        workflow.state.value == "awaiting_approval"
                        and workflow.approval is None
                        and not workflow.work_orders
                    )
                    detail = f"state={workflow.state.value}, work_orders={len(workflow.work_orders)}"
                else:
                    plan = next(
                        (plan for plan in workflow.verified_plans() if plan.profile == "balanced"),
                        workflow.verified_plans()[0],
                    )
                    workflow.approve(plan.plan_id, "adversarial_operator", case_id)
                    if attack == "tampered_plan":
                        plan.scheduled_operations[0].line_id = "line_assembly"
                    elif attack == "stale_approval":
                        workflow.scenario_hash = "stale_hash"
                    elif attack == "evidence_revoked":
                        plan.evidence.verified = False
                    else:
                        raise ValueError(f"unknown attack: {attack}")
                    try:
                        workflow.generate_orders()
                        detail = f"attack {attack} bypassed gate"
                    except (ValueError, RuntimeError):
                        passed = True
                        detail = f"attack {attack} blocked"

            elif case["type"] == "verifier_attack":
                workflow = _run_workflow(
                    scenario_path,
                    suite_path.parent / case["incident"],
                )
                plan = workflow.verified_plans()[0].model_copy(deep=True)
                plan.scheduled_operations[0].line_id = "line_assembly"
                violations = verify_plan(workflow.adjusted_scenario, plan)
                passed = any("not eligible" in violation for violation in violations)
                detail = f"violations={violations[:2]}"

            elif case["type"] == "deterministic_replay":
                first = _run_workflow(
                    scenario_path,
                    suite_path.parent / case["incident"],
                )
                second = _run_workflow(
                    scenario_path,
                    suite_path.parent / case["incident"],
                )
                first_plans = [
                    plan.model_dump(mode="json", exclude={"evidence": {"solve_time_ms"}})
                    for plan in first.plans
                ]
                second_plans = [
                    plan.model_dump(mode="json", exclude={"evidence": {"solve_time_ms"}})
                    for plan in second.plans
                ]
                passed = first.scenario_hash == second.scenario_hash and first_plans == second_plans
                detail = f"scenario_hash={first.scenario_hash[:12]}"
            else:
                raise ValueError(f"unknown case type: {case['type']}")
        except Exception as exc:  # keep the whole suite observable
            passed = False
            detail = f"unexpected {type(exc).__name__}: {exc}"

        case_results.append({"case_id": case_id, "passed": passed, "detail": detail})
        if not passed:
            invariant_violations.append(f"{case_id}: {detail}")

    return {
        "suite_id": suite["suite_id"],
        "as_of": suite["as_of"],
        "total_cases": len(case_results),
        "passed_cases": sum(result["passed"] for result in case_results),
        "failed_cases": sum(not result["passed"] for result in case_results),
        "invariant_violations": invariant_violations,
        "cases": case_results,
    }
