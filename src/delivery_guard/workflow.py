"""Explicit workflow and approval gates for the recovery decision loop."""

from __future__ import annotations

from delivery_guard.data import apply_incident, scenario_incident_hash
from delivery_guard.hashing import candidate_plan_hash, stable_hash
from delivery_guard.impact import analyze_impact
from delivery_guard.models import (
    ApprovalDecision,
    AuditEvent,
    CandidatePlan,
    ImpactReport,
    Incident,
    Scenario,
    WorkflowState,
    WorkOrderDraft,
)
from delivery_guard.orders import generate_work_order_drafts
from delivery_guard.solver import solve_profiles


class RecoveryWorkflow:
    def __init__(self, scenario: Scenario, incident: Incident) -> None:
        self.base_scenario = scenario
        self.incident = incident
        self.adjusted_scenario: Scenario | None = None
        self.scenario_hash: str | None = None
        self.impact: ImpactReport | None = None
        self.plans: list[CandidatePlan] = []
        self.approval: ApprovalDecision | None = None
        self.work_orders: list[WorkOrderDraft] = []
        self.state = WorkflowState.RECEIVED
        self.audit: list[AuditEvent] = []
        self._record(None, WorkflowState.RECEIVED, "system", "Scenario and incident received")

    def _state_payload(self) -> dict:
        return {
            "state": self.state.value,
            "scenario_hash": self.scenario_hash,
            "impact": self.impact,
            "plans": self.plans,
            "approval": self.approval,
            "work_orders": self.work_orders,
        }

    def _record(
        self,
        from_state: WorkflowState | None,
        to_state: WorkflowState,
        actor_type: str,
        summary: str,
    ) -> None:
        self.state = to_state
        self.audit.append(
            AuditEvent(
                sequence=len(self.audit) + 1,
                from_state=from_state,
                to_state=to_state,
                actor_type=actor_type,
                summary=summary,
                state_hash=stable_hash(self._state_payload()),
            )
        )

    def analyze(self) -> ImpactReport:
        if self.state != WorkflowState.RECEIVED:
            raise RuntimeError(f"analyze not allowed from {self.state}")
        before = self.state
        self.adjusted_scenario = apply_incident(self.base_scenario, self.incident)
        self.scenario_hash = scenario_incident_hash(self.base_scenario, self.incident)
        self._record(before, WorkflowState.VALIDATED, "deterministic_tool", "Inputs validated")
        before = self.state
        self.impact = analyze_impact(
            self.base_scenario,
            self.adjusted_scenario,
            self.incident,
            self.scenario_hash,
        )
        self._record(before, WorkflowState.ANALYZED, "deterministic_tool", "Impact graph computed")
        return self.impact

    def solve(self) -> list[CandidatePlan]:
        if self.state != WorkflowState.ANALYZED:
            raise RuntimeError(f"solve not allowed from {self.state}")
        self.plans = solve_profiles(self.adjusted_scenario, self.scenario_hash)
        before = self.state
        self._record(before, WorkflowState.SOLVED, "solver", "Three policy profiles solved")
        before = self.state
        self._record(
            before,
            WorkflowState.AWAITING_APPROVAL,
            "system",
            "Verified candidates are awaiting explicit approval",
        )
        return self.plans

    def verified_plans(self) -> list[CandidatePlan]:
        return [plan for plan in self.plans if plan.evidence and plan.evidence.verified]

    def approve(self, plan_id: str, actor_id: str, comment: str) -> ApprovalDecision:
        if self.state != WorkflowState.AWAITING_APPROVAL:
            raise RuntimeError(f"approve not allowed from {self.state}")
        plan = next((plan for plan in self.plans if plan.plan_id == plan_id), None)
        if plan is None:
            raise ValueError(f"unknown plan_id {plan_id}")
        if not plan.evidence or not plan.evidence.verified:
            raise ValueError("cannot approve a plan without passing solver and independent verification")
        current_plan_hash = candidate_plan_hash(plan)
        if current_plan_hash != plan.evidence.plan_hash:
            raise ValueError("plan changed after verification; re-solve is required")
        if plan.scenario_hash != self.scenario_hash:
            raise ValueError("stale plan scenario hash")
        self.approval = ApprovalDecision(
            approval_id=f"approval_{len(self.audit) + 1:03d}",
            plan_id=plan.plan_id,
            scenario_hash=self.scenario_hash,
            plan_hash=current_plan_hash,
            decision="approve",
            actor_id=actor_id,
            comment=comment,
        )
        before = self.state
        self._record(before, WorkflowState.APPROVED, "user", f"Plan {plan_id} approved")
        return self.approval

    def reject(self, plan_id: str, actor_id: str, comment: str) -> ApprovalDecision:
        if self.state != WorkflowState.AWAITING_APPROVAL:
            raise RuntimeError(f"reject not allowed from {self.state}")
        plan = next((plan for plan in self.plans if plan.plan_id == plan_id), None)
        if plan is None:
            raise ValueError(f"unknown plan_id {plan_id}")
        self.approval = ApprovalDecision(
            approval_id=f"approval_{len(self.audit) + 1:03d}",
            plan_id=plan.plan_id,
            scenario_hash=self.scenario_hash,
            plan_hash=candidate_plan_hash(plan),
            decision="reject",
            actor_id=actor_id,
            comment=comment,
        )
        before = self.state
        self._record(before, WorkflowState.REJECTED, "user", f"Plan {plan_id} rejected")
        return self.approval

    def generate_orders(self) -> list[WorkOrderDraft]:
        if self.state != WorkflowState.APPROVED or not self.approval:
            raise RuntimeError("work orders require a valid approved state")
        plan = next(plan for plan in self.plans if plan.plan_id == self.approval.plan_id)
        if self.approval.scenario_hash != self.scenario_hash:
            self.approval.valid = False
            raise ValueError("approval is stale because scenario hash changed")
        if self.approval.plan_hash != candidate_plan_hash(plan):
            self.approval.valid = False
            raise ValueError("approval is stale because plan hash changed")
        if not plan.evidence or not plan.evidence.verified:
            raise ValueError("plan verification evidence is no longer valid")
        self.work_orders = generate_work_order_drafts(plan, self.approval)
        before = self.state
        self._record(
            before,
            WorkflowState.ORDERS_GENERATED,
            "deterministic_tool",
            f"Generated {len(self.work_orders)} draft-only work orders",
        )
        return self.work_orders

    def invalidate(self, reason: str, actor_type: str = "external_tool") -> None:
        """Invalidate every active plan and approval after a confirmed fact changes."""

        if self.state == WorkflowState.STALE:
            return
        before = self.state
        if self.approval:
            self.approval.valid = False
        self.work_orders = []
        self._record(before, WorkflowState.STALE, actor_type, f"Plan invalidated: {reason}")

    def export(self) -> dict:
        return {
            "scenario_hash": self.scenario_hash,
            "incident": self.incident.model_dump(mode="json"),
            "state": self.state.value,
            "impact": self.impact.model_dump(mode="json") if self.impact else None,
            "plans": [plan.model_dump(mode="json") for plan in self.plans],
            "approval": self.approval.model_dump(mode="json") if self.approval else None,
            "work_orders": [order.model_dump(mode="json") for order in self.work_orders],
            "audit": [event.model_dump(mode="json") for event in self.audit],
        }
