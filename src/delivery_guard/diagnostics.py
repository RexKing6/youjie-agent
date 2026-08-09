"""Deterministic business summaries and plan-difference diagnostics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from delivery_guard.models import CandidatePlan, Scenario
from delivery_guard.impact import explode_bom


def _task_key(task: Any) -> tuple[str, str]:
    return task.order_id, task.operation_id


def summarize_plan(
    scenario: Scenario,
    plan: CandidatePlan,
    baseline: CandidatePlan | None = None,
) -> dict[str, Any]:
    """Return user-facing metrics computed from plan facts, never from language output."""

    order_map = {order.order_id: order for order in scenario.orders}
    outcome_map = {outcome.order_id: outcome for outcome in plan.order_outcomes}
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total_units": 0,
            "on_time_units": 0,
            "late_units": 0,
            "unscheduled_units": 0,
            "max_late_hours": 0,
            "customer_name": None,
            "due_hour": None,
        }
    )
    for order in scenario.orders:
        group_id = order.order_group_id or order.order_id
        group = groups[group_id]
        group["total_units"] += order.quantity
        group["customer_name"] = order.customer_name or group_id
        group["due_hour"] = order.due_hour if group["due_hour"] is None else min(
            group["due_hour"], order.due_hour
        )
        outcome = outcome_map[order.order_id]
        if not outcome.scheduled:
            group["unscheduled_units"] += order.quantity
        elif outcome.late_hours:
            group["late_units"] += order.quantity
            group["max_late_hours"] = max(group["max_late_hours"], outcome.late_hours)
        else:
            group["on_time_units"] += order.quantity

    overtime_order_ids = {
        task.order_id for task in plan.scheduled_operations if task.overtime
    }
    changed_order_ids: set[str] = set()
    if baseline is not None:
        current_tasks = {_task_key(task): task for task in plan.scheduled_operations}
        baseline_tasks = {_task_key(task): task for task in baseline.scheduled_operations}
        for key in set(current_tasks) | set(baseline_tasks):
            current = current_tasks.get(key)
            previous = baseline_tasks.get(key)
            if current is None or previous is None:
                changed_order_ids.add(key[0])
                continue
            if (current.line_id, current.start_hour, current.end_hour) != (
                previous.line_id,
                previous.start_hour,
                previous.end_hour,
            ):
                changed_order_ids.add(key[0])

    return {
        "profile": plan.profile,
        "recovery_cost": plan.objective_breakdown.get("recovery_cost", 0),
        "overtime_cost": plan.objective_breakdown.get("overtime_cost", 0),
        "overtime_units": sum(order_map[order_id].quantity for order_id in overtime_order_ids),
        "alternate_supplier_units": sum(
            purchase.quantity for purchase in plan.purchases if not purchase.committed
        ),
        "supplier_changes": sum(1 for purchase in plan.purchases if not purchase.committed),
        "first_due_on_time_units": plan.objective_breakdown.get("first_due_on_time_units", 0),
        "first_due_late_units": plan.objective_breakdown.get("first_due_late_units", 0),
        "schedule_changes": len(changed_order_ids),
        "changed_order_ids": sorted(changed_order_ids),
        "groups": dict(sorted(groups.items())),
    }


def material_shortfall_explanation(
    required: dict[str, int],
    available: dict[str, int],
) -> list[dict[str, int | str]]:
    """Return exact shortages for an infeasible request without an LLM estimate."""

    return [
        {
            "item_id": item_id,
            "required": quantity,
            "maximum_available": available.get(item_id, 0),
            "shortfall": quantity - available.get(item_id, 0),
        }
        for item_id, quantity in sorted(required.items())
        if quantity > available.get(item_id, 0)
    ]


def diagnose_product_request(
    scenario: Scenario,
    *,
    product_id: str,
    requested_total_units: int,
    due_hour: int,
) -> dict[str, Any]:
    """Prove a product-level request bound from material arrivals and line calendars.

    This is a conservative aggregate capacity diagnostic. It never changes an order,
    invents a supplier, or claims a feasible sequence; a candidate still needs CP-SAT
    and the independent verifier.
    """

    if requested_total_units <= 0:
        raise ValueError("requested_total_units must be positive")
    unit_requirements, _ = explode_bom(scenario, product_id, 1)
    operation = next(
        item for item in scenario.route_operations if item.product_id == product_id
    )
    eligible_lines = [
        line
        for line in scenario.production_lines
        if line.line_type in operation.eligible_line_types
    ]

    def available_material(cutoff: int) -> dict[str, int]:
        totals: dict[str, int] = defaultdict(int)
        for entry in scenario.inventory:
            totals[entry.item_id] += entry.available
        for source in scenario.supplier_sources:
            if source.enabled and source.lead_time_hours <= cutoff:
                totals[source.item_id] += source.max_quantity
        return dict(totals)

    def line_capacity(cutoff: int) -> int:
        batches = 0
        for line in eligible_lines:
            windows = line.available_windows or [
                type("Window", (), {"start_hour": 0, "end_hour": scenario.horizon_hours})()
            ]
            for window in windows:
                usable = max(0, min(window.end_hour, cutoff) - window.start_hour)
                batches += usable // operation.duration_per_batch_hours
        return batches * operation.batch_size

    def bound(cutoff: int) -> dict[str, Any]:
        available = available_material(cutoff)
        material_bounds = {
            item_id: available.get(item_id, 0) // quantity_per_unit
            for item_id, quantity_per_unit in unit_requirements.items()
        }
        capacity_units = line_capacity(cutoff)
        limiting_units = min([capacity_units, *material_bounds.values()])
        maximum_units = min(requested_total_units, limiting_units)
        return {
            "cutoff_hour": cutoff,
            "maximum_units": maximum_units,
            "requested_units": requested_total_units,
            "shortfall_units": requested_total_units - maximum_units,
            "material_unit_bounds": dict(sorted(material_bounds.items())),
            "line_capacity_units": capacity_units,
        }

    due_bound = bound(due_hour)
    horizon_bound = bound(scenario.horizon_hours)
    earliest_full_hour = None
    for cutoff in range(0, scenario.horizon_hours + 1, 4):
        if bound(cutoff)["maximum_units"] >= requested_total_units:
            earliest_full_hour = cutoff
            break

    horizon_material = available_material(scenario.horizon_hours)
    material_shortfalls = material_shortfall_explanation(
        {
            item_id: quantity_per_unit * requested_total_units
            for item_id, quantity_per_unit in unit_requirements.items()
        },
        horizon_material,
    )
    capacity_shortfall_units = max(
        0, requested_total_units - horizon_bound["line_capacity_units"]
    )
    feasible_by_due = due_bound["maximum_units"] >= requested_total_units
    feasible_within_horizon = horizon_bound["maximum_units"] >= requested_total_units
    return {
        "diagnostic_type": "aggregate_resource_upper_bound",
        "product_id": product_id,
        "requested_total_units": requested_total_units,
        "due_hour": due_hour,
        "feasible_by_due": feasible_by_due,
        "feasible_within_horizon": feasible_within_horizon,
        "maximum_deliverable_by_due": due_bound["maximum_units"],
        "maximum_deliverable_within_horizon": horizon_bound["maximum_units"],
        "earliest_full_delivery_hour": earliest_full_hour,
        "due_bound": due_bound,
        "horizon_bound": horizon_bound,
        "minimum_additional_material": material_shortfalls,
        "minimum_additional_capacity_units": capacity_shortfall_units,
        "alternatives": [
            {
                "alternative": "cap_commitment_at_due_bound",
                "deliverable_units": due_bound["maximum_units"],
                "deadline_hour": due_hour,
            },
            {
                "alternative": "cap_commitment_at_horizon_bound",
                "deliverable_units": horizon_bound["maximum_units"],
                "deadline_hour": scenario.horizon_hours,
            },
            {
                "alternative": "request_additional_resources",
                "material_shortfalls": material_shortfalls,
                "capacity_shortfall_units": capacity_shortfall_units,
            },
        ],
        "claim_boundary": (
            "Upper-bound diagnosis only; any executable schedule must still be solved and "
            "independently verified."
        ),
    }
