"""Constrained industrial Agent that delegates every business fact to typed tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from delivery_guard.context import (
    AgentMessage,
    AgentTaskState,
    RecoveryAuthorization,
    TaskContext,
)
from delivery_guard.data import load_scenario
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.explanations import grounded_plan_explanation
from delivery_guard.knowledge import LocalKnowledgeBase
from delivery_guard.llm import LanguageModel
from delivery_guard.models import CandidatePlan, Incident, Scenario
from delivery_guard.parsing import (
    confirm_incident,
    parse_incident_draft,
    resolve_and_validate_draft,
)
from delivery_guard.solver import solve_candidate
from delivery_guard.tools import AgentToolbox
from delivery_guard.workflow import RecoveryWorkflow


class DeliveryGuardAgent:
    """Single-Agent control plane; solver and verifier remain authoritative."""

    def __init__(
        self,
        *,
        scenario_path: str | Path,
        knowledge_paths: list[str | Path],
        model: LanguageModel,
        task_id: str = "task_delivery_crisis",
    ) -> None:
        self.scenario_path = Path(scenario_path)
        self.base_scenario = load_scenario(self.scenario_path)
        self.scenario = self.base_scenario
        self.model = model
        self.knowledge = LocalKnowledgeBase(knowledge_paths)
        self.context = TaskContext(
            task_id=task_id,
            model_mode=model.mode,
            model_name=model.model_name,
        )
        self.toolbox = AgentToolbox(self.context, self.scenario, self.knowledge)
        self.raw_incident_text: str | None = None
        self.raw_incident_source: str | None = None
        self.incident: Incident | None = None
        self.workflow: RecoveryWorkflow | None = None
        self.baseline_plan: CandidatePlan | None = None
        self.plan_summaries: dict[str, dict[str, Any]] = {}
        self.explanations: dict[str, dict[str, Any]] = {}

    def ingest(
        self,
        raw_text: str,
        *,
        source_ref: str,
        replay_key: str,
    ) -> TaskContext:
        if self.context.state not in {
            AgentTaskState.COLLECTING,
            AgentTaskState.NEEDS_CLARIFICATION,
        }:
            raise RuntimeError(f"ingest not allowed from {self.context.state}")
        self.raw_incident_text = raw_text
        self.raw_incident_source = source_ref
        self.context.messages.append(
            AgentMessage(role="user", content=raw_text, source_ref=source_ref)
        )
        draft = parse_incident_draft(
            self.model,
            replay_key=replay_key,
            raw_text=raw_text,
            source_ref=source_ref,
        )
        draft = resolve_and_validate_draft(draft, self.scenario)
        self.context.incident_draft = draft
        self.context.add_trace(
            "parse_incident",
            {"source_ref": source_ref, "model_mode": self.model.mode},
            {
                "incident_kind": draft.incident_kind,
                "resolved_target_id": draft.resolved_target_id,
                "missing_fields": draft.missing_fields,
                "required_confirmations": draft.required_confirmations,
                "security_flags": draft.security_flags,
            },
            source_refs=[source_ref],
        )
        self.toolbox.query_factory_snapshot()
        for query in (
            "ColdChain A Retail B split delivery customer SLA",
            "Beta emergency MCU approved alternate supplier limit premium",
            "Friday overtime maximum units cost approval",
        ):
            self.toolbox.retrieve_policy(query, top_k=2)
        if draft.missing_fields or draft.conflicts or draft.required_confirmations:
            self.context.state = AgentTaskState.NEEDS_CLARIFICATION
        else:
            self.context.state = AgentTaskState.READY_TO_CONFIRM
        return self.context

    def clarification_prompt(self) -> list[str]:
        draft = self.context.incident_draft
        if draft is None:
            return ["请先提供异常信息。"]
        prompts = [f"请确认缺失字段：{field}" for field in draft.missing_fields]
        prompts.extend(f"请处理来源冲突：{conflict}" for conflict in draft.conflicts)
        if "approve_beta_limit" in draft.required_confirmations:
            prompts.append("是否授权使用备选供应商 Beta？若授权，最多采购多少颗 MCU？")
        if "approve_overtime_limit" in draft.required_confirmations:
            prompts.append("是否授权周五加班？若授权，最多生产多少台？")
        return prompts

    def _authorized_scenario(self, authorization: RecoveryAuthorization) -> Scenario:
        payload = self.base_scenario.model_dump(mode="json")
        payload["scenario_version"] += 1
        for source in payload["supplier_sources"]:
            if source["source_id"] == "src_beta_mcu_emergency":
                if authorization.allow_beta:
                    source["max_quantity"] = min(
                        source["max_quantity"], authorization.beta_max_quantity
                    )
                else:
                    source["max_quantity"] = 0
                    source["enabled"] = False
        updated_lines = []
        for line in payload["production_lines"]:
            if line["line_id"] != "line_smt_overtime":
                updated_lines.append(line)
                continue
            if not authorization.allow_overtime or authorization.overtime_max_units == 0:
                continue
            max_lots = min(2, authorization.overtime_max_units // 10)
            if max_lots:
                line["available_windows"] = [
                    {"start_hour": 104, "end_hour": 104 + 4 * max_lots}
                ]
                updated_lines.append(line)
        payload["production_lines"] = updated_lines
        return Scenario.model_validate(payload)

    def authorize_and_solve(self, authorization: RecoveryAuthorization) -> dict[str, Any]:
        draft = self.context.incident_draft
        if draft is None or self.raw_incident_text is None or self.raw_incident_source is None:
            raise RuntimeError("incident must be ingested first")
        if draft.missing_fields or draft.conflicts:
            raise ValueError("cannot solve with missing fields or conflicts")
        self.context.authorization = authorization
        self.context.messages.append(
            AgentMessage(
                role="user",
                content=(
                    f"Authorization by {authorization.actor_id}: beta={authorization.beta_max_quantity} "
                    f"overtime={authorization.overtime_max_units}. {authorization.comment}"
                ),
            )
        )
        self.incident = confirm_incident(
            draft,
            self.raw_incident_text,
            self.raw_incident_source,
        )
        self.context.state = AgentTaskState.CONFIRMED
        self.scenario = self._authorized_scenario(authorization)
        self.toolbox = AgentToolbox(self.context, self.scenario, self.knowledge)
        self.baseline_plan = solve_candidate(
            self.scenario,
            "baseline_pre_incident",
            "service_first",
        )
        self.workflow = self.toolbox.analyze_and_solve(self.incident)
        self.context.state = AgentTaskState.AWAITING_APPROVAL
        self.plan_summaries = {
            plan.profile: summarize_plan(
                self.workflow.adjusted_scenario,
                plan,
                self.baseline_plan,
            )
            for plan in self.workflow.plans
        }
        deduped_citations = {
            (citation.document_id, citation.section, citation.text): citation
            for citation in self.context.retrieved_evidence
        }
        citations = list(deduped_citations.values())
        self.explanations = {
            profile: grounded_plan_explanation(summary, citations)
            for profile, summary in self.plan_summaries.items()
        }
        return {
            "context": self.context,
            "impact": self.workflow.impact,
            "plans": self.workflow.plans,
            "summaries": self.plan_summaries,
            "explanations": self.explanations,
        }

    def approve(self, profile: str, *, actor_id: str, comment: str) -> list:
        if self.workflow is None:
            raise RuntimeError("no workflow to approve")
        plan = next(
            plan
            for plan in self.workflow.verified_plans()
            if plan.profile == profile
        )
        self.workflow.approve(plan.plan_id, actor_id, comment)
        drafts = self.workflow.generate_orders()
        self.context.active_plan_hash = plan.evidence.plan_hash
        self.context.state = AgentTaskState.COMPLETED
        self.context.add_trace(
            "draft_actions",
            {"profile": profile, "actor_id": actor_id},
            {"draft_count": len(drafts), "execution_status": "draft_only"},
            source_refs=[plan.evidence.evidence_id, self.workflow.approval.approval_id],
        )
        return drafts

    def record_external_supplier_confirmation(
        self,
        *,
        source_id: str,
        confirmed_quantity: int,
        source_ref: str,
    ) -> dict[str, Any]:
        if self.workflow is None or self.incident is None or self.context.authorization is None:
            raise RuntimeError("external feedback requires an existing solved workflow")
        self.workflow.invalidate(
            f"{source_id} confirmed only {confirmed_quantity} units",
            actor_type="external_tool",
        )
        self.context.state = AgentTaskState.STALE
        self.context.stale_reason = f"{source_id} confirmed {confirmed_quantity}"
        self.context.active_plan_hash = None
        payload = self.base_scenario.model_dump(mode="json")
        payload["scenario_version"] += 2
        for source in payload["supplier_sources"]:
            if source["source_id"] == source_id:
                source["max_quantity"] = min(source["max_quantity"], confirmed_quantity)
        self.base_scenario = Scenario.model_validate(payload)
        revised_authorization = self.context.authorization.model_copy(
            update={"beta_max_quantity": min(
                self.context.authorization.beta_max_quantity,
                confirmed_quantity,
            )}
        )
        self.context.add_trace(
            "record_external_feedback",
            {"source_id": source_id, "source_ref": source_ref},
            {
                "confirmed_quantity": confirmed_quantity,
                "previous_plan_stale": True,
                "draft_actions_blocked": True,
            },
            source_refs=[source_ref],
        )
        result = self.authorize_and_solve(revised_authorization)
        result["replanned_after_feedback"] = True
        return result

    def export(self) -> dict[str, Any]:
        return {
            "context": self.context.model_dump(mode="json"),
            "incident": self.incident.model_dump(mode="json") if self.incident else None,
            "workflow": self.workflow.export() if self.workflow else None,
            "plan_summaries": self.plan_summaries,
            "explanations": self.explanations,
        }
