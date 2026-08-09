"""Typed read/solve tools exposed to the constrained language Agent."""

from __future__ import annotations

from typing import Any, Callable

from delivery_guard.context import TaskContext
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.knowledge import LocalKnowledgeBase
from delivery_guard.models import Incident, Scenario
from delivery_guard.workflow import RecoveryWorkflow


class AgentToolbox:
    def __init__(
        self,
        context: TaskContext,
        scenario: Scenario,
        knowledge: LocalKnowledgeBase,
        scenario_source_ref: str = "data/cases/delivery_crisis/scenario.json",
    ) -> None:
        self.context = context
        self.scenario = scenario
        self.knowledge = knowledge
        self.scenario_source_ref = scenario_source_ref

    def query_factory_snapshot(self) -> dict[str, Any]:
        result = {
            "scenario_id": self.scenario.scenario_id,
            "orders": len(self.scenario.orders),
            "commercial_order_groups": len({
                order.order_group_id or order.order_id for order in self.scenario.orders
            }),
            "inventory_items": len(self.scenario.inventory),
            "supplier_sources": len(self.scenario.supplier_sources),
            "production_lines": len(self.scenario.production_lines),
            "scenario_version": self.scenario.scenario_version,
        }
        self.context.add_trace(
            "query_factory_snapshot",
            {"scenario_id": self.scenario.scenario_id},
            result,
            source_refs=[self.scenario_source_ref],
        )
        return result

    def retrieve_policy(self, query: str, top_k: int = 4) -> list:
        citations = self.knowledge.search(query, top_k=top_k)
        self.context.retrieved_evidence.extend(citations)
        self.context.add_trace(
            "retrieve_policy",
            {"query": query, "top_k": top_k},
            {
                "citations": [citation.citation_id for citation in citations],
                "security_flags": sorted({
                    flag for citation in citations for flag in citation.security_flags
                }),
            },
            source_refs=[citation.source_ref for citation in citations],
        )
        return citations

    def analyze_and_solve(self, incident: Incident) -> RecoveryWorkflow:
        workflow = RecoveryWorkflow(self.scenario, incident)
        impact = workflow.analyze()
        plans = workflow.solve()
        self.context.scenario_hash = workflow.scenario_hash
        self.context.add_trace(
            "analyze_impact",
            {"incident_id": incident.incident_id, "target_id": incident.target_id},
            {
                "affected_orders": len(impact.affected_orders),
                "shortages": impact.projected_shortages,
                "scenario_hash": workflow.scenario_hash,
            },
            source_refs=[incident.source_ref, self.scenario_source_ref],
        )
        self.context.add_trace(
            "solve_recovery",
            {"profiles": [plan.profile for plan in plans]},
            {
                "verified_profiles": [
                    plan.profile for plan in plans if plan.evidence and plan.evidence.verified
                ],
                "summaries": [
                    summarize_plan(workflow.adjusted_scenario, plan) for plan in plans
                ],
            },
            source_refs=["OR-Tools CP-SAT", "independent verifier"],
        )
        return workflow
