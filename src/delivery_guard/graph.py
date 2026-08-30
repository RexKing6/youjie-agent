"""LangGraph orchestration for explainable, solver-verified incident response."""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from delivery_guard.context import IncidentDraft, TaskContext
from delivery_guard.data import apply_incident, load_scenario
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.hashing import candidate_plan_hash
from delivery_guard.knowledge import LocalKnowledgeBase
from delivery_guard.llm import LanguageModel
from delivery_guard.models import Incident
from delivery_guard.parsing import confirm_incident, parse_incident_draft, resolve_and_validate_draft
from delivery_guard.tools import AgentToolbox
from delivery_guard.workflow import RecoveryWorkflow


class GuardGraphState(TypedDict, total=False):
    entry_mode: str
    raw_text: str
    source_ref: str
    replay_key: str
    incident_draft: dict[str, Any]
    incident: dict[str, Any]
    planned_actions: list[dict[str, Any]]
    snapshot: dict[str, Any]
    citations: list[dict[str, Any]]
    impact: dict[str, Any]
    plans: list[dict[str, Any]]
    plan_summaries: dict[str, dict[str, Any]]
    scenario_hash: str
    decision: dict[str, Any]
    workflow: dict[str, Any]
    work_orders: list[dict[str, Any]]
    status: str
    model_mode: str
    model_name: str
    preflight_conflicts: list[str]
    preflight_required_confirmations: list[str]
    previous_graph_result: dict[str, Any]
    previous_scenario_hash: str
    previous_plan_hash: str
    previous_approval_id: str
    previous_approval_valid: bool
    feedback_metadata: dict[str, Any]
    graph_trace: Annotated[list[dict[str, Any]], operator.add]
    tool_traces: Annotated[list[dict[str, Any]], operator.add]


POLICY_QUERIES = {
    "supplier_delay": [
        "supplier lead time capacity emergency source approval",
        "customer due date late delivery human confirmation",
    ],
    "supplier_shutdown": [
        "supplier shutdown alternate source capacity approval",
        "industrial safety human confirmation",
    ],
    "inventory_loss": [
        "inventory discrepancy quality hold replan",
        "industrial safety human confirmation",
    ],
    "line_outage": [
        "line outage production capacity safe replan",
        "industrial safety no equipment control human confirmation",
    ],
    "demand_surge": [
        "demand surge customer due date commit boundary",
        "capacity material availability human confirmation",
    ],
}


class DeliveryGuardGraph:
    """One bounded Agent graph; mathematical and approval authority stay outside the LLM."""

    def __init__(
        self,
        *,
        scenario_path: str | Path,
        knowledge_paths: list[str | Path],
        model: LanguageModel,
    ) -> None:
        self.scenario_path = Path(scenario_path)
        self.scenario = load_scenario(self.scenario_path)
        self.knowledge = LocalKnowledgeBase(knowledge_paths)
        self.model = model
        self.graph = self._compile()

    @property
    def topology(self) -> list[str]:
        return sorted(self.graph.get_graph().nodes)

    @staticmethod
    def _trace(node: str, summary: str) -> list[dict[str, Any]]:
        return [{"node": node, "summary": summary}]

    @staticmethod
    def _route_entry(state: GuardGraphState) -> str:
        return (
            "receive_execution_feedback"
            if state.get("entry_mode") == "execution_feedback"
            else "understand_incident"
        )

    def _scenario_for_state(self, state: GuardGraphState):
        if state.get("entry_mode") != "execution_feedback":
            return self.scenario
        previous = state.get("previous_graph_result") or {}
        original_payload = (
            (previous.get("workflow") or {}).get("incident")
            or previous.get("incident")
        )
        if not original_payload:
            raise ValueError("original incident is required for feedback re-plan")
        return apply_incident(self.scenario, Incident.model_validate(original_payload))

    def _receive_execution_feedback(self, state: GuardGraphState) -> dict[str, Any]:
        previous = state.get("previous_graph_result") or {}
        previous_workflow = previous.get("workflow") or {}
        previous_approval = previous_workflow.get("approval") or {}
        feedback = state.get("feedback_metadata") or {}
        Incident.model_validate(state["incident"])
        if previous.get("status") != "completed":
            raise ValueError("feedback re-plan requires a completed graph result")
        if previous_approval.get("decision") != "approve" or previous_approval.get("valid") is not True:
            raise ValueError("feedback re-plan requires a valid previous approval")
        if feedback.get("changed") is not True:
            raise ValueError("unchanged feedback must not invalidate an approval")
        before = str(feedback.get("source_revision_before", ""))
        after = str(feedback.get("source_revision_after", ""))
        if not before or not after or before == after:
            raise ValueError("feedback must provide two different source revisions")
        return {
            "status": "execution_feedback_received",
            "previous_scenario_hash": previous_workflow.get("scenario_hash", ""),
            "previous_plan_hash": previous_approval.get("plan_hash", ""),
            "previous_approval_id": previous_approval.get("approval_id", ""),
            "previous_approval_valid": True,
            "work_orders": [],
            "graph_trace": self._trace(
                "receive_execution_feedback",
                f"Accepted typed execution feedback {before} -> {after}; no new action was created.",
            ),
        }

    @staticmethod
    def _invalidate_stale_approval(state: GuardGraphState) -> dict[str, Any]:
        return {
            "status": "approval_invalidated",
            "previous_approval_valid": False,
            "work_orders": [],
            "graph_trace": [{
                "node": "invalidate_stale_approval",
                "summary": (
                    f"Invalidated {state['previous_approval_id']} because a planning dependency changed; "
                    "fresh solver evidence and a new human decision are required."
                ),
            }],
        }

    def _understand(self, state: GuardGraphState) -> dict[str, Any]:
        if state.get("incident"):
            incident = Incident.model_validate(state["incident"])
            return {
                "incident": incident.model_dump(mode="json"),
                "status": "incident_validated",
                "graph_trace": self._trace(
                    "understand_incident",
                    "Validated structured chaos-drill ground truth; communication remains untrusted display text.",
                ),
            }
        draft = parse_incident_draft(
            self.model,
            replay_key=state["replay_key"],
            raw_text=state["raw_text"],
            source_ref=state["source_ref"],
        )
        draft = resolve_and_validate_draft(draft, self.scenario)
        draft.conflicts = sorted(set([
            *draft.conflicts,
            *state.get("preflight_conflicts", []),
        ]))
        draft.required_confirmations = sorted(set([
            *draft.required_confirmations,
            *state.get("preflight_required_confirmations", []),
        ]))
        return {
            "incident_draft": draft.model_dump(mode="json"),
            "status": "needs_clarification" if (
                draft.missing_fields or draft.conflicts or draft.required_confirmations
            ) else "incident_understood",
            "graph_trace": self._trace(
                "understand_incident",
                f"Produced IncidentDraft in {self.model.mode} mode with source spans.",
            ),
            "tool_traces": [{
                "tool_name": "parse_incident",
                "success": True,
                "input_summary": {"source_ref": state["source_ref"], "model_mode": self.model.mode},
                "result_summary": {
                    "incident_kind": draft.incident_kind,
                    "target_id": draft.resolved_target_id,
                    "missing_fields": draft.missing_fields,
                    "security_flags": draft.security_flags,
                },
                "source_refs": [state["source_ref"]],
            }],
        }

    @staticmethod
    def _route_after_understand(state: GuardGraphState) -> str:
        if state.get("incident"):
            return "plan_investigation"
        draft = IncidentDraft.model_validate(state["incident_draft"])
        if draft.missing_fields or draft.conflicts or draft.required_confirmations:
            return "clarify_incident"
        return "plan_investigation"

    def _clarify(self, state: GuardGraphState) -> dict[str, Any]:
        draft = IncidentDraft.model_validate(state["incident_draft"])
        response = interrupt({
            "type": "incident_clarification",
            "missing_fields": draft.missing_fields,
            "conflicts": draft.conflicts,
            "required_confirmations": draft.required_confirmations,
            "instruction": "Provide corrected fields and explicit confirmations; no solve occurs before this gate.",
        })
        if not isinstance(response, dict):
            raise ValueError("clarification response must be an object")
        allowed = {
            "incident_kind", "target_mention", "resolved_target_id", "delay_hours",
            "loss_quantity", "start_hour", "end_hour", "quantity_delta", "source_spans",
        }
        updated = draft.model_dump(mode="json")
        updated.update({key: value for key, value in response.items() if key in allowed})
        if response.get("confirmations_accepted") is True:
            updated["required_confirmations"] = []
        updated["missing_fields"] = response.get("missing_fields", [])
        updated["conflicts"] = response.get("conflicts", [])
        revised = resolve_and_validate_draft(IncidentDraft.model_validate(updated), self.scenario)
        return {
            "incident_draft": revised.model_dump(mode="json"),
            "status": "incident_clarified",
            "graph_trace": self._trace("clarify_incident", "Human clarification was validated against domain IDs."),
        }

    def _plan_investigation(self, state: GuardGraphState) -> dict[str, Any]:
        if state.get("incident"):
            kind = Incident.model_validate(state["incident"]).kind.value
        else:
            kind = IncidentDraft.model_validate(state["incident_draft"]).incident_kind
        queries = POLICY_QUERIES[kind]
        actions = [
            {"tool": "query_factory_snapshot", "reason": "Establish frozen business context"},
            *[
                {"tool": "retrieve_policy", "query": query, "reason": "Retrieve bounded evidence"}
                for query in queries
            ],
            {"tool": "analyze_impact", "reason": "Compute BOM and order propagation"},
            {"tool": "solve_recovery", "reason": "Generate solver-verified candidates"},
        ]
        return {
            "planned_actions": actions,
            "status": "investigation_planned",
            "graph_trace": self._trace(
                "plan_investigation",
                f"Selected {len(actions)} allowlisted actions for {kind}.",
            ),
        }

    def _investigate(self, state: GuardGraphState) -> dict[str, Any]:
        scenario = self._scenario_for_state(state)
        context = TaskContext(
            task_id="langgraph_investigation",
            model_mode=state.get("model_mode", self.model.mode),
            model_name=state.get("model_name", self.model.model_name),
        )
        toolbox = AgentToolbox(
            context,
            scenario,
            self.knowledge,
            scenario_source_ref=str(self.scenario_path),
        )
        snapshot = toolbox.query_factory_snapshot()
        for action in state["planned_actions"]:
            if action["tool"] == "retrieve_policy":
                toolbox.retrieve_policy(action["query"], top_k=2)

        incident_payload = state.get("incident")
        if not incident_payload:
            draft = IncidentDraft.model_validate(state["incident_draft"])
            incident_payload = confirm_incident(
                draft,
                state["raw_text"],
                state["source_ref"],
            ).model_dump(mode="json")
        return {
            "incident": incident_payload,
            "snapshot": snapshot,
            "citations": [item.model_dump(mode="json") for item in context.retrieved_evidence],
            "tool_traces": [item.model_dump(mode="json") for item in context.tool_traces],
            "status": "evidence_collected",
            "graph_trace": self._trace(
                "execute_investigation",
                f"Executed snapshot plus {len(context.retrieved_evidence)} cited policy results.",
            ),
        }

    def _analyze_and_solve(self, state: GuardGraphState) -> dict[str, Any]:
        incident = Incident.model_validate(state["incident"])
        scenario = self._scenario_for_state(state)
        context = TaskContext(
            task_id="langgraph_solver",
            model_mode=state.get("model_mode", self.model.mode),
            model_name=state.get("model_name", self.model.model_name),
        )
        toolbox = AgentToolbox(
            context,
            scenario,
            self.knowledge,
            scenario_source_ref=str(self.scenario_path),
        )
        workflow = toolbox.analyze_and_solve(incident)
        summaries = {
            plan.profile: summarize_plan(workflow.adjusted_scenario, plan)
            for plan in workflow.plans
        }
        return {
            "impact": workflow.impact.model_dump(mode="json"),
            "plans": [plan.model_dump(mode="json") for plan in workflow.plans],
            "plan_summaries": summaries,
            "scenario_hash": workflow.scenario_hash,
            "workflow": workflow.export(),
            "tool_traces": [item.model_dump(mode="json") for item in context.tool_traces],
            "status": "awaiting_approval",
            "graph_trace": self._trace(
                "analyze_and_solve",
                "Deterministic impact, CP-SAT, and independent verification completed.",
            ),
        }

    def _human_approval(self, state: GuardGraphState) -> dict[str, Any]:
        response = interrupt({
            "type": "plan_approval",
            "scenario_hash": state["scenario_hash"],
            "plans": state["plan_summaries"],
            "instruction": "Choose approve/reject. Approval requires actor_id, comment, and a verified profile.",
        })
        if not isinstance(response, dict):
            raise ValueError("approval response must be an object")
        decision = response.get("decision")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if not response.get("actor_id") or not str(response.get("comment", "")).strip():
            raise ValueError("actor_id and non-empty comment are required")
        if decision == "approve":
            profile = response.get("profile")
            selected = next((plan for plan in state["plans"] if plan["profile"] == profile), None)
            if selected is None or not selected.get("evidence", {}).get("verified"):
                raise ValueError("only a solver-verified profile can be approved")
        return {
            "decision": response,
            "status": "approved" if decision == "approve" else "rejected",
            "graph_trace": self._trace("human_approval", f"Human chose {decision}."),
        }

    @staticmethod
    def _route_after_approval(state: GuardGraphState) -> str:
        return "draft_actions" if state["decision"]["decision"] == "approve" else "finish_rejected"

    def _draft_actions(self, state: GuardGraphState) -> dict[str, Any]:
        incident = Incident.model_validate(state["incident"])
        workflow = RecoveryWorkflow(self._scenario_for_state(state), incident)
        workflow.analyze()
        workflow.solve()
        profile = state["decision"]["profile"]
        selected = next(plan for plan in workflow.verified_plans() if plan.profile == profile)
        stored = next(plan for plan in state["plans"] if plan["profile"] == profile)
        if selected.scenario_hash != state["scenario_hash"]:
            raise ValueError("scenario changed after human review")
        if candidate_plan_hash(selected) != stored["evidence"]["plan_hash"]:
            raise ValueError("recomputed plan differs from reviewed plan")
        workflow.approve(
            selected.plan_id,
            actor_id=state["decision"]["actor_id"],
            comment=state["decision"]["comment"],
        )
        work_orders = workflow.generate_orders()
        return {
            "workflow": workflow.export(),
            "work_orders": [item.model_dump(mode="json") for item in work_orders],
            "status": "completed",
            "graph_trace": self._trace(
                "draft_actions",
                f"Generated {len(work_orders)} draft-only actions after hash recheck.",
            ),
        }

    @staticmethod
    def _finish_rejected(_state: GuardGraphState) -> dict[str, Any]:
        return {
            "work_orders": [],
            "status": "rejected",
            "graph_trace": [{"node": "finish_rejected", "summary": "No actions were generated."}],
        }

    def _compile(self):
        builder = StateGraph(GuardGraphState)
        builder.add_node("understand_incident", self._understand)
        builder.add_node("clarify_incident", self._clarify)
        builder.add_node("receive_execution_feedback", self._receive_execution_feedback)
        builder.add_node("invalidate_stale_approval", self._invalidate_stale_approval)
        builder.add_node("plan_investigation", self._plan_investigation)
        builder.add_node("execute_investigation", self._investigate)
        builder.add_node("analyze_and_solve", self._analyze_and_solve)
        builder.add_node("human_approval", self._human_approval)
        builder.add_node("draft_actions", self._draft_actions)
        builder.add_node("finish_rejected", self._finish_rejected)
        builder.add_conditional_edges(
            START,
            self._route_entry,
            {
                "understand_incident": "understand_incident",
                "receive_execution_feedback": "receive_execution_feedback",
            },
        )
        builder.add_edge("receive_execution_feedback", "invalidate_stale_approval")
        builder.add_edge("invalidate_stale_approval", "plan_investigation")
        builder.add_conditional_edges(
            "understand_incident",
            self._route_after_understand,
            {
                "clarify_incident": "clarify_incident",
                "plan_investigation": "plan_investigation",
            },
        )
        builder.add_conditional_edges(
            "clarify_incident",
            self._route_after_understand,
            {
                "clarify_incident": "clarify_incident",
                "plan_investigation": "plan_investigation",
            },
        )
        builder.add_edge("plan_investigation", "execute_investigation")
        builder.add_edge("execute_investigation", "analyze_and_solve")
        builder.add_edge("analyze_and_solve", "human_approval")
        builder.add_conditional_edges(
            "human_approval",
            self._route_after_approval,
            {
                "draft_actions": "draft_actions",
                "finish_rejected": "finish_rejected",
            },
        )
        builder.add_edge("draft_actions", END)
        builder.add_edge("finish_rejected", END)
        return builder.compile(checkpointer=InMemorySaver())

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def start(
        self,
        *,
        raw_text: str,
        source_ref: str,
        replay_key: str,
        thread_id: str,
        preflight_conflicts: list[str] | None = None,
        preflight_required_confirmations: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.graph.invoke(
            {
                "entry_mode": "incident",
                "raw_text": raw_text,
                "source_ref": source_ref,
                "replay_key": replay_key,
                "model_mode": self.model.mode,
                "model_name": self.model.model_name,
                "preflight_conflicts": preflight_conflicts or [],
                "preflight_required_confirmations": preflight_required_confirmations or [],
                "graph_trace": [],
                "tool_traces": [],
            },
            config=self._config(thread_id),
        )

    def start_drill(self, *, drill: Any, thread_id: str) -> dict[str, Any]:
        return self.graph.invoke(
            {
                "entry_mode": "incident",
                "raw_text": drill.body,
                "source_ref": drill.incident.source_ref,
                "replay_key": "structured_chaos_drill",
                "incident": drill.incident.model_dump(mode="json"),
                "model_mode": "structured_drill",
                "model_name": "chaos-drill-agent-v1",
                "graph_trace": [],
                "tool_traces": [],
            },
            config=self._config(thread_id),
        )

    def start_feedback(
        self,
        *,
        previous_graph_result: dict[str, Any],
        feedback_incident: Incident | dict[str, Any],
        source_revision_before: str,
        source_revision_after: str,
        thread_id: str,
        source_system: str = "mes",
    ) -> dict[str, Any]:
        incident = (
            feedback_incident
            if isinstance(feedback_incident, Incident)
            else Incident.model_validate(feedback_incident)
        )
        return self.graph.invoke(
            {
                "entry_mode": "execution_feedback",
                "previous_graph_result": previous_graph_result,
                "incident": incident.model_dump(mode="json"),
                "feedback_metadata": {
                    "changed": True,
                    "source_system": source_system,
                    "source_revision_before": source_revision_before,
                    "source_revision_after": source_revision_after,
                },
                "model_mode": "typed_execution_feedback",
                "model_name": "deterministic-feedback-adapter-v1",
                "graph_trace": [],
                "tool_traces": [],
            },
            config=self._config(thread_id),
        )

    def resume(self, *, thread_id: str, response: dict[str, Any]) -> dict[str, Any]:
        return self.graph.invoke(Command(resume=response), config=self._config(thread_id))
