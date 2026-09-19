"""OR-Tools CP-SAT recovery planner with independent verification evidence."""

from __future__ import annotations

import time
from collections import defaultdict

import ortools
from ortools.sat.python import cp_model

from delivery_guard.hashing import candidate_plan_hash
from delivery_guard.impact import explode_bom
from delivery_guard.models import (
    CandidatePlan,
    FeasibilityEvidence,
    OrderOutcome,
    Priority,
    PurchaseAction,
    Scenario,
    ScheduledOperation,
)
from delivery_guard.verifier import verify_plan


PROFILE_WEIGHTS = {
    "service_first": {"unfulfilled": 1_000_000, "lateness": 10_000, "cost": 1, "actions": 50},
    "balanced": {"unfulfilled": 1_000_000, "lateness": 5_000, "cost": 10, "actions": 200},
    "stability_first": {"unfulfilled": 1_000_000, "lateness": 3_000, "cost": 30, "actions": 1_000},
}

PLANNING_STEP_HOURS = 4


def solve_candidate(
    scenario: Scenario,
    scenario_hash: str,
    profile: str,
    time_limit_seconds: float = 5.0,
    objective_mode: str = "weighted",
) -> CandidatePlan:
    if profile not in PROFILE_WEIGHTS:
        raise ValueError(f"unknown profile: {profile}")
    if objective_mode not in {"weighted", "lexicographic"}:
        raise ValueError("unknown objective mode")
    weights = PROFILE_WEIGHTS[profile]
    model = cp_model.CpModel()
    horizon = scenario.horizon_hours

    operations_by_product: dict[str, list] = defaultdict(list)
    for operation in scenario.route_operations:
        operations_by_product[operation.product_id].append(operation)
    for product_id in operations_by_product:
        operations_by_product[product_id].sort(key=lambda operation: operation.sequence)

    line_map = {line.line_id: line for line in scenario.production_lines}
    lines_by_type: dict[str, list] = defaultdict(list)
    for line in scenario.production_lines:
        lines_by_type[line.line_type].append(line)

    scheduled_vars: dict[str, cp_model.IntVar] = {}
    assignment_vars: dict[tuple[str, str, str, int], cp_model.IntVar] = {}
    task_start_expr: dict[tuple[str, str], cp_model.LinearExpr] = {}
    task_end_expr: dict[tuple[str, str], cp_model.LinearExpr] = {}
    task_duration: dict[tuple[str, str], int] = {}
    line_hour_terms: dict[tuple[str, int], list] = defaultdict(list)
    line_recovery_terms = []
    constraints_count = defaultdict(int)

    for order in scenario.orders:
        scheduled = model.new_bool_var(f"scheduled__{order.order_id}")
        scheduled_vars[order.order_id] = scheduled
        if order.priority == Priority.CRITICAL or order.frozen or profile == "service_first":
            model.add(scheduled == 1)
            constraints_count["required_order"] += 1

        previous_end = None
        for operation in operations_by_product[order.product_id]:
            duration = (
                (order.quantity + operation.batch_size - 1) // operation.batch_size
            ) * operation.duration_per_batch_hours
            task_key = (order.order_id, operation.operation_id)
            task_duration[task_key] = duration
            candidates = []
            for line_type in operation.eligible_line_types:
                for line in lines_by_type[line_type]:
                    first_start = (
                        (order.release_hour + PLANNING_STEP_HOURS - 1)
                        // PLANNING_STEP_HOURS
                    ) * PLANNING_STEP_HOURS
                    for start in range(
                        first_start,
                        horizon - duration + 1,
                        PLANNING_STEP_HOURS,
                    ):
                        end = start + duration
                        if not line.permits(start, end):
                            continue
                        variable = model.new_bool_var(
                            f"x__{order.order_id}__{operation.operation_id}__{line.line_id}__{start}"
                        )
                        assignment_vars[(order.order_id, operation.operation_id, line.line_id, start)] = variable
                        candidates.append((line.line_id, start, variable))
                        if line.incremental_cost_per_batch:
                            line_recovery_terms.append(line.incremental_cost_per_batch * variable)
                        for hour in range(start, end):
                            line_hour_terms[(line.line_id, hour)].append(variable)
            if not candidates:
                model.add(scheduled == 0)
                constraints_count["no_candidate"] += 1
                task_start_expr[task_key] = 0
                task_end_expr[task_key] = 0
                continue
            model.add(sum(variable for _, _, variable in candidates) == scheduled)
            constraints_count["task_assignment"] += 1
            start_expr = sum(start * variable for _, start, variable in candidates)
            end_expr = start_expr + duration * scheduled
            task_start_expr[task_key] = start_expr
            task_end_expr[task_key] = end_expr
            if previous_end is not None:
                model.add(start_expr >= previous_end)
                constraints_count["precedence"] += 1
            previous_end = end_expr

    for terms in line_hour_terms.values():
        model.add(sum(terms) <= 1)
        constraints_count["line_capacity"] += 1

    purchase_vars: dict[str, cp_model.IntVar] = {}
    purchase_used_vars: dict[str, cp_model.IntVar] = {}
    for source in scenario.supplier_sources:
        upper = source.max_quantity if source.enabled and source.lead_time_hours <= horizon else 0
        lower = source.committed_quantity if upper else 0
        quantity = model.new_int_var(lower, upper, f"purchase__{source.source_id}")
        used = model.new_bool_var(f"purchase_used__{source.source_id}")
        model.add(quantity > 0).only_enforce_if(used)
        model.add(quantity == 0).only_enforce_if(used.Not())
        purchase_vars[source.source_id] = quantity
        purchase_used_vars[source.source_id] = used
        constraints_count["supplier_capacity"] += 2

    initial_inventory = defaultdict(int)
    for entry in scenario.inventory:
        initial_inventory[entry.item_id] += entry.available

    first_operation_by_product = {
        product_id: operations[0] for product_id, operations in operations_by_product.items()
    }
    requirements_by_order = {
        order.order_id: explode_bom(scenario, order.product_id, order.quantity)[0]
        for order in scenario.orders
    }
    material_ids = set(initial_inventory) | {source.item_id for source in scenario.supplier_sources}
    inventory_event_hours = {0, horizon}
    inventory_event_hours.update(
        source.lead_time_hours
        for source in scenario.supplier_sources
        if source.lead_time_hours <= horizon
    )
    first_assignment_terms: dict[str, list[tuple[int, cp_model.IntVar]]] = defaultdict(list)
    for order in scenario.orders:
        first_operation = first_operation_by_product[order.product_id]
        for (order_id, operation_id, _line_id, start), variable in assignment_vars.items():
            if order_id == order.order_id and operation_id == first_operation.operation_id:
                first_assignment_terms[order.order_id].append((start, variable))
                inventory_event_hours.add(start)
    for material_id in material_ids:
        relevant_sources = [
            source for source in scenario.supplier_sources if source.item_id == material_id
        ]
        for hour in sorted(inventory_event_hours):
            consumption_terms = []
            for order in scenario.orders:
                required = requirements_by_order[order.order_id].get(material_id, 0)
                if not required:
                    continue
                for start, variable in first_assignment_terms[order.order_id]:
                    if start <= hour:
                        consumption_terms.append(required * variable)
            arrived_supply = [
                purchase_vars[source.source_id]
                for source in relevant_sources
                if source.lead_time_hours <= hour
            ]
            model.add(
                sum(consumption_terms) <= initial_inventory[material_id] + sum(arrived_supply)
            )
            constraints_count["inventory_balance"] += 1

    priority_multiplier = {Priority.CRITICAL: 5, Priority.HIGH: 3, Priority.NORMAL: 1}
    unfulfilled_terms = []
    lateness_vars: dict[str, cp_model.IntVar] = {}
    for order in scenario.orders:
        scheduled = scheduled_vars[order.order_id]
        unfulfilled_terms.append((1 - scheduled) * order.quantity * priority_multiplier[order.priority])
        last_operation = operations_by_product[order.product_id][-1]
        completion = task_end_expr[(order.order_id, last_operation.operation_id)]
        lateness = model.new_int_var(0, horizon, f"lateness__{order.order_id}")
        model.add(lateness >= completion - order.due_hour)
        model.add(lateness <= horizon * scheduled)
        lateness_vars[order.order_id] = lateness
        constraints_count["lateness"] += 2

    unfulfilled_score = sum(unfulfilled_terms)
    lateness_score = sum(
        lateness_vars[order.order_id] * order.quantity * priority_multiplier[order.priority]
        for order in scenario.orders
    )
    purchase_cost = sum(
        purchase_vars[source.source_id] * source.unit_cost for source in scenario.supplier_sources
    )
    recovery_purchase_cost = sum(
        purchase_vars[source.source_id] * source.recovery_unit_cost
        for source in scenario.supplier_sources
    )
    line_recovery_cost = sum(line_recovery_terms)
    recovery_cost = recovery_purchase_cost + line_recovery_cost
    action_count = sum(
        purchase_used_vars[source.source_id]
        for source in scenario.supplier_sources
        if source.committed_quantity == 0
    )
    if profile in scenario.profile_recovery_budgets:
        model.add(recovery_cost <= scenario.profile_recovery_budgets[profile])
        constraints_count["recovery_budget"] += 1
    objective = (
        weights["unfulfilled"] * unfulfilled_score
        + weights["lateness"] * lateness_score
        + weights["cost"] * recovery_cost
        + weights["actions"] * action_count
    )
    model.minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    started = time.perf_counter()
    status_code = solver.solve(model) if objective_mode == "weighted" else cp_model.UNKNOWN
    lex_proven = 0
    if objective_mode == "lexicographic":
        # Explicit priority stages; never claim weighted arithmetic is lexicographic.
        # Keep the last feasible solution if a later priority exhausts the shared limit.
        stages = [unfulfilled_score, lateness_score, recovery_cost, action_count, sum(task_start_expr.values())]
        last_feasible = None
        for stage in stages:
            remaining = time_limit_seconds - (time.perf_counter()-started)
            if remaining <= 0:
                break
            model.minimize(stage)
            candidate_solver = cp_model.CpSolver()
            candidate_solver.parameters.max_time_in_seconds = remaining
            candidate_solver.parameters.num_search_workers = 1
            candidate_solver.parameters.random_seed = 0
            candidate_status = candidate_solver.solve(model)
            if candidate_status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                last_feasible = candidate_solver
            if candidate_status != cp_model.OPTIMAL:
                break
            lex_proven += 1
            model.add(stage == candidate_solver.value(stage))
        if last_feasible is not None:
            solver = last_feasible
            status_code = cp_model.OPTIMAL if lex_proven == len(stages) else cp_model.FEASIBLE
    solve_time_ms = int((time.perf_counter() - started) * 1000)
    status_name = solver.status_name(status_code)

    scheduled_operations: list[ScheduledOperation] = []
    purchases: list[PurchaseAction] = []
    outcomes: list[OrderOutcome] = []
    objective_breakdown = {
        "unfulfilled_weighted_units": 0,
        "lateness_weighted_units_hours": 0,
        "purchase_cost": 0,
        "recovery_cost": 0,
        "overtime_cost": 0,
        "purchase_actions": 0,
        "on_time_units": 0,
        "late_units": 0,
        "unscheduled_units": 0,
        "first_due_on_time_units": 0,
        "first_due_late_units": 0,
    }
    total_score = 0

    if status_code in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        for (order_id, operation_id, line_id, start), variable in assignment_vars.items():
            if solver.value(variable):
                duration = task_duration[(order_id, operation_id)]
                scheduled_operations.append(
                    ScheduledOperation(
                        task_id=f"{order_id}__{operation_id}",
                        order_id=order_id,
                        operation_id=operation_id,
                        line_id=line_id,
                        start_hour=start,
                        end_hour=start + duration,
                        incremental_cost=line_map[line_id].incremental_cost_per_batch,
                        overtime=line_map[line_id].overtime,
                    )
                )
        supplier_map = {supplier.supplier_id: supplier for supplier in scenario.suppliers}
        for source in scenario.supplier_sources:
            quantity = solver.value(purchase_vars[source.source_id])
            if quantity:
                purchases.append(
                    PurchaseAction(
                        source_id=source.source_id,
                        supplier_id=source.supplier_id,
                        item_id=source.item_id,
                        quantity=quantity,
                        arrival_hour=source.lead_time_hours,
                        cost=quantity * source.unit_cost,
                        incremental_cost=quantity * source.recovery_unit_cost,
                        committed=source.committed_quantity > 0,
                    )
                )
                _ = supplier_map[source.supplier_id]
        tasks_by_order: dict[str, list[ScheduledOperation]] = defaultdict(list)
        for task in scheduled_operations:
            tasks_by_order[task.order_id].append(task)
        for order in scenario.orders:
            scheduled = bool(solver.value(scheduled_vars[order.order_id]))
            completion = max(
                (task.end_hour for task in tasks_by_order[order.order_id]),
                default=None,
            )
            outcomes.append(
                OrderOutcome(
                    order_id=order.order_id,
                    scheduled=scheduled,
                    completion_hour=completion,
                    late_hours=solver.value(lateness_vars[order.order_id]),
                )
            )
        objective_breakdown = {
            "unfulfilled_weighted_units": solver.value(unfulfilled_score),
            "lateness_weighted_units_hours": solver.value(lateness_score),
            "purchase_cost": solver.value(purchase_cost),
            "recovery_cost": solver.value(recovery_cost),
            "overtime_cost": solver.value(line_recovery_cost),
            "purchase_actions": solver.value(action_count),
            "on_time_units": sum(
                order.quantity
                for order in scenario.orders
                if solver.value(scheduled_vars[order.order_id])
                and solver.value(lateness_vars[order.order_id]) == 0
            ),
            "late_units": sum(
                order.quantity
                for order in scenario.orders
                if solver.value(scheduled_vars[order.order_id])
                and solver.value(lateness_vars[order.order_id]) > 0
            ),
            "unscheduled_units": sum(
                order.quantity
                for order in scenario.orders
                if not solver.value(scheduled_vars[order.order_id])
            ),
            "first_due_on_time_units": sum(
                order.quantity
                for order in scenario.orders
                if order.due_hour == min(item.due_hour for item in scenario.orders)
                and solver.value(scheduled_vars[order.order_id])
                and solver.value(lateness_vars[order.order_id]) == 0
            ),
            "first_due_late_units": sum(
                order.quantity
                for order in scenario.orders
                if order.due_hour == min(item.due_hour for item in scenario.orders)
                and (
                    not solver.value(scheduled_vars[order.order_id])
                    or solver.value(lateness_vars[order.order_id]) > 0
                )
            ),
        }
        total_score = int(solver.value(objective)) if objective_mode == "lexicographic" else int(solver.objective_value)
        if objective_mode == "lexicographic":
            objective_breakdown["lexicographic_stages_proven"] = lex_proven
            objective_breakdown["lexicographic_stages_total"] = 5
    else:
        for order in scenario.orders:
            outcomes.append(
                OrderOutcome(
                    order_id=order.order_id,
                    scheduled=False,
                    completion_hour=None,
                    late_hours=0,
                )
            )

    bare_plan = CandidatePlan(
        plan_id=f"plan_{profile}",
        profile=profile,
        scenario_hash=scenario_hash,
        scheduled_operations=sorted(
            scheduled_operations,
            key=lambda task: (task.start_hour, task.line_id, task.task_id),
        ),
        purchases=sorted(purchases, key=lambda purchase: purchase.source_id),
        order_outcomes=sorted(outcomes, key=lambda outcome: outcome.order_id),
        objective_breakdown=objective_breakdown,
        total_score=total_score,
        assumptions=[
            *(["Lexicographic priority: unfulfilled, lateness, incremental cost, action count, earliest start; total_score is only a weighted comparison index."] if objective_mode == "lexicographic" else []),
            "All purchase orders are placed at planning hour 0.",
            f"Candidate operation starts use a {PLANNING_STEP_HOURS}-hour planning grid.",
            "Time and quantity are integer-scaled; no real ERP write is performed.",
        ],
        risks=[
            "Scenario data is public-derived and synthetic, not live factory data.",
            "Supplier capacity is modeled as a horizon-level cap in this MVP.",
        ],
    )
    plan_hash = candidate_plan_hash(bare_plan)
    violations = []
    if status_code in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        violations = verify_plan(scenario, bare_plan)
    evidence = FeasibilityEvidence(
        evidence_id=f"evidence_{profile}",
        solver_name="OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        solver_status=status_name,
        solve_time_ms=solve_time_ms,
        scenario_hash=scenario_hash,
        plan_hash=plan_hash,
        verified=status_code in {cp_model.OPTIMAL, cp_model.FEASIBLE} and not violations,
        violations=violations,
        objective_breakdown=objective_breakdown,
        constraint_counts=dict(sorted(constraints_count.items())),
    )
    return bare_plan.model_copy(update={"evidence": evidence})


def solve_profiles(scenario: Scenario, scenario_hash: str, *, objective_mode: str = "weighted") -> list[CandidatePlan]:
    return [
        solve_candidate(scenario, scenario_hash, profile, objective_mode=objective_mode)
        for profile in ("service_first", "balanced", "stability_first")
    ]
