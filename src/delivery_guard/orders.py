"""Generate non-executable, fully traceable work-order drafts."""

from __future__ import annotations

from delivery_guard.models import ApprovalDecision, CandidatePlan, WorkOrderDraft


def generate_work_order_drafts(
    plan: CandidatePlan,
    approval: ApprovalDecision,
) -> list[WorkOrderDraft]:
    drafts: list[WorkOrderDraft] = []

    def add(work_order_type: str, payload: dict) -> None:
        drafts.append(
            WorkOrderDraft(
                work_order_id=f"wo_{len(drafts) + 1:03d}",
                work_order_type=work_order_type,
                approved_plan_id=plan.plan_id,
                approval_id=approval.approval_id,
                scenario_hash=plan.scenario_hash,
                payload=payload,
            )
        )

    for purchase in plan.purchases:
        add(
            "supplier_purchase_request",
            {
                "source_id": purchase.source_id,
                "supplier_id": purchase.supplier_id,
                "item_id": purchase.item_id,
                "quantity": purchase.quantity,
                "expected_arrival_hour": purchase.arrival_hour,
                "estimated_cost": purchase.cost,
                "requires_external_execution": True,
            },
        )

    for outcome in plan.order_outcomes:
        if outcome.scheduled:
            tasks = [
                task.model_dump(mode="json")
                for task in plan.scheduled_operations
                if task.order_id == outcome.order_id
            ]
            add(
                "schedule_change_order",
                {
                    "order_id": outcome.order_id,
                    "completion_hour": outcome.completion_hour,
                    "late_hours": outcome.late_hours,
                    "tasks": tasks,
                    "requires_external_execution": True,
                },
            )
        else:
            add(
                "customer_communication_task",
                {
                    "order_id": outcome.order_id,
                    "reason": "No solver-verified schedule within the planning horizon",
                    "requires_human_contact": True,
                },
            )
    return drafts
