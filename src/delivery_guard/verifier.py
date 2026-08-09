"""Independent plan verifier that does not trust CP-SAT status."""

from __future__ import annotations

from collections import defaultdict

from delivery_guard.impact import explode_bom
from delivery_guard.models import CandidatePlan, Scenario


def verify_plan(scenario: Scenario, plan: CandidatePlan) -> list[str]:
    violations: list[str] = []
    line_map = {line.line_id: line for line in scenario.production_lines}
    source_map = {source.source_id: source for source in scenario.supplier_sources}
    order_map = {order.order_id: order for order in scenario.orders}
    operations_by_product = {
        product_id: sorted(
            [op for op in scenario.route_operations if op.product_id == product_id],
            key=lambda op: op.sequence,
        )
        for product_id in {order.product_id for order in scenario.orders}
    }

    tasks_by_order: dict[str, list] = defaultdict(list)
    for task in plan.scheduled_operations:
        tasks_by_order[task.order_id].append(task)
        if task.line_id not in line_map:
            violations.append(f"{task.task_id}: unknown line {task.line_id}")
            continue
        line = line_map[task.line_id]
        if task.start_hour < 0 or task.end_hour > scenario.horizon_hours:
            violations.append(f"{task.task_id}: outside planning horizon")
        if task.end_hour <= task.start_hour:
            violations.append(f"{task.task_id}: non-positive duration")
        if not line.permits(task.start_hour, task.end_hour):
            violations.append(f"{task.task_id}: outside line availability on {task.line_id}")
        if task.incremental_cost != line.incremental_cost_per_batch:
            violations.append(f"{task.task_id}: incorrect line incremental cost")
        if task.overtime != line.overtime:
            violations.append(f"{task.task_id}: overtime flag mismatch")

    for line_id in line_map:
        line_tasks = sorted(
            [task for task in plan.scheduled_operations if task.line_id == line_id],
            key=lambda task: task.start_hour,
        )
        for left, right in zip(line_tasks, line_tasks[1:]):
            if left.end_hour > right.start_hour:
                violations.append(
                    f"line overlap {line_id}: {left.task_id} ends {left.end_hour}, "
                    f"{right.task_id} starts {right.start_hour}"
                )

    outcome_map = {outcome.order_id: outcome for outcome in plan.order_outcomes}
    for order_id, order in order_map.items():
        outcome = outcome_map.get(order_id)
        if outcome is None:
            violations.append(f"missing outcome for {order_id}")
            continue
        tasks = tasks_by_order[order_id]
        expected_operations = operations_by_product[order.product_id]
        if not outcome.scheduled:
            if tasks:
                violations.append(f"{order_id}: unscheduled outcome has operations")
            if order.priority.value == "critical" or order.frozen:
                violations.append(f"{order_id}: critical/frozen order was not scheduled")
            continue
        if len(tasks) != len(expected_operations):
            violations.append(
                f"{order_id}: expected {len(expected_operations)} operations, got {len(tasks)}"
            )
            continue
        task_by_operation = {task.operation_id: task for task in tasks}
        previous_end = order.release_hour
        for operation in expected_operations:
            task = task_by_operation.get(operation.operation_id)
            if task is None:
                violations.append(f"{order_id}: missing {operation.operation_id}")
                continue
            line = line_map.get(task.line_id)
            if line and line.line_type not in operation.eligible_line_types:
                violations.append(
                    f"{task.task_id}: line type {line.line_type} not eligible for {operation.operation_id}"
                )
            expected_duration = (
                (order.quantity + operation.batch_size - 1) // operation.batch_size
            ) * operation.duration_per_batch_hours
            if task.end_hour - task.start_hour != expected_duration:
                violations.append(
                    f"{task.task_id}: duration {task.end_hour - task.start_hour} != {expected_duration}"
                )
            if task.start_hour < previous_end:
                violations.append(
                    f"{task.task_id}: starts {task.start_hour} before predecessor/release {previous_end}"
                )
            previous_end = task.end_hour
        expected_completion = previous_end
        if outcome.completion_hour != expected_completion:
            violations.append(
                f"{order_id}: completion {outcome.completion_hour} != {expected_completion}"
            )
        expected_late = max(0, expected_completion - order.due_hour)
        if outcome.late_hours != expected_late:
            violations.append(f"{order_id}: late_hours {outcome.late_hours} != {expected_late}")

    purchases_by_material_hour: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    purchased_by_source: dict[str, int] = defaultdict(int)
    for purchase in plan.purchases:
        source = source_map.get(purchase.source_id)
        if source is None:
            violations.append(f"purchase references unknown source {purchase.source_id}")
            continue
        if not source.enabled:
            violations.append(f"purchase uses disabled source {purchase.source_id}")
        if purchase.item_id != source.item_id or purchase.supplier_id != source.supplier_id:
            violations.append(f"purchase source identity mismatch {purchase.source_id}")
        if purchase.arrival_hour != source.lead_time_hours:
            violations.append(
                f"purchase {purchase.source_id}: arrival {purchase.arrival_hour} "
                f"!= lead time {source.lead_time_hours}"
            )
        if purchase.cost != purchase.quantity * source.unit_cost:
            violations.append(f"purchase {purchase.source_id}: incorrect cost")
        if purchase.incremental_cost != purchase.quantity * source.recovery_unit_cost:
            violations.append(f"purchase {purchase.source_id}: incorrect incremental cost")
        if purchase.committed != (source.committed_quantity > 0):
            violations.append(f"purchase {purchase.source_id}: committed flag mismatch")
        purchased_by_source[purchase.source_id] += purchase.quantity
        purchases_by_material_hour[purchase.item_id][purchase.arrival_hour] += purchase.quantity

    for source_id, quantity in purchased_by_source.items():
        source = source_map[source_id]
        if quantity < source.committed_quantity:
            violations.append(
                f"source {source_id}: purchased {quantity} < committed {source.committed_quantity}"
            )
        if quantity > source.max_quantity:
            violations.append(
                f"source {source_id}: purchased {quantity} > capacity {source.max_quantity}"
            )

    recovery_cost = sum(purchase.incremental_cost for purchase in plan.purchases) + sum(
        task.incremental_cost for task in plan.scheduled_operations
    )
    budget = scenario.profile_recovery_budgets.get(plan.profile)
    if budget is not None and recovery_cost > budget:
        violations.append(f"recovery cost {recovery_cost} exceeds {plan.profile} budget {budget}")

    inventory = defaultdict(int)
    for entry in scenario.inventory:
        inventory[entry.item_id] += entry.available

    consumption_by_material_hour: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for outcome in plan.order_outcomes:
        if not outcome.scheduled:
            continue
        order = order_map[outcome.order_id]
        tasks = tasks_by_order[outcome.order_id]
        if not tasks:
            continue
        first_start = min(task.start_hour for task in tasks)
        requirements, _ = explode_bom(scenario, order.product_id, order.quantity)
        for item_id, quantity in requirements.items():
            consumption_by_material_hour[item_id][first_start] += quantity

    all_materials = set(inventory) | set(purchases_by_material_hour) | set(consumption_by_material_hour)
    for hour in range(scenario.horizon_hours + 1):
        for item_id in all_materials:
            inventory[item_id] += purchases_by_material_hour[item_id].get(hour, 0)
            inventory[item_id] -= consumption_by_material_hour[item_id].get(hour, 0)
            if inventory[item_id] < 0:
                violations.append(f"{item_id}: inventory is {inventory[item_id]} at hour {hour}")

    return sorted(set(violations))
