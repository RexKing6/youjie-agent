from pathlib import Path

from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.llm import ReplayLanguageModel
from delivery_guard.models import Incident, IncidentKind


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/cases/mendeley_drill"


def build_graph():
    return DeliveryGuardGraph(
        scenario_path=CASE / "scenario.json",
        knowledge_paths=[
            CASE / "customer_sla.md",
            CASE / "procurement_policy.md",
            CASE / "safety_policy.md",
        ],
        model=ReplayLanguageModel(ROOT / "data/model_replays/mendeley_drill.json"),
    )


def start(graph, thread_id):
    return graph.start(
        raw_text=(CASE / "supplier_delay_email.txt").read_text(encoding="utf-8"),
        source_ref="data/cases/mendeley_drill/supplier_delay_email.txt",
        replay_key="mendeley_seat_delay_email",
        thread_id=thread_id,
    )


def test_langgraph_runs_to_real_human_interrupt_then_hash_checked_drafts():
    graph = build_graph()
    assert {
        "understand_incident",
        "plan_investigation",
        "execute_investigation",
        "analyze_and_solve",
        "human_approval",
        "draft_actions",
        "receive_execution_feedback",
        "invalidate_stale_approval",
    }.issubset(graph.topology)
    waiting = start(graph, "graph-approve")
    assert waiting["status"] == "awaiting_approval"
    assert waiting["__interrupt__"]
    assert waiting["plan_summaries"]["balanced"]["first_due_on_time_units"] == 45
    assert {trace["tool_name"] for trace in waiting["tool_traces"]} >= {
        "parse_incident", "query_factory_snapshot", "retrieve_policy", "analyze_impact", "solve_recovery"
    }
    completed = graph.resume(
        thread_id="graph-approve",
        response={
            "decision": "approve",
            "profile": "balanced",
            "actor_id": "planner_test",
            "comment": "Approve only draft actions in the isolated drill.",
        },
    )
    assert completed["status"] == "completed"
    assert completed["work_orders"]
    assert completed["workflow"]["state"] == "orders_generated"
    assert completed["workflow"]["approval"]["valid"] is True


def test_execution_feedback_reenters_langgraph_and_requires_fresh_approval():
    graph = build_graph()
    start(graph, "graph-feedback-original")
    completed = graph.resume(
        thread_id="graph-feedback-original",
        response={
            "decision": "approve",
            "profile": "balanced",
            "actor_id": "planner_test",
            "comment": "Approve the original isolated drill.",
        },
    )
    feedback_incident = Incident(
        incident_id="inc_test_mes_feedback",
        kind=IncidentKind.LINE_OUTAGE,
        target_id="line_zp7_public",
        description="Typed MES feedback reports a newly confirmed outage.",
        start_hour=48,
        end_hour=68,
        source_type="mes_test_callback",
        source_ref="/tests/mes/callback",
    )

    replanned = graph.start_feedback(
        previous_graph_result=completed,
        feedback_incident=feedback_incident,
        source_revision_before="mes-rev-12",
        source_revision_after="mes-rev-13",
        source_system="mes_test",
        thread_id="graph-feedback-replan",
    )

    trace = [item["node"] for item in replanned["graph_trace"]]
    assert trace == [
        "receive_execution_feedback",
        "invalidate_stale_approval",
        "plan_investigation",
        "execute_investigation",
        "analyze_and_solve",
    ]
    assert replanned["status"] == "awaiting_approval"
    assert replanned["previous_approval_valid"] is False
    assert replanned["previous_approval_id"] == completed["workflow"]["approval"]["approval_id"]
    assert replanned["scenario_hash"] != replanned["previous_scenario_hash"]
    assert replanned["work_orders"] == []
    assert replanned["__interrupt__"]

    refreshed = graph.resume(
        thread_id="graph-feedback-replan",
        response={
            "decision": "approve",
            "profile": "balanced",
            "actor_id": "planner_test",
            "comment": "Approve only the freshly recomputed draft actions.",
        },
    )
    assert refreshed["status"] == "completed"
    assert refreshed["workflow"]["approval"]["scenario_hash"] == refreshed["scenario_hash"]
    assert refreshed["workflow"]["approval"]["scenario_hash"] != replanned["previous_scenario_hash"]
    assert refreshed["workflow"]["approval"]["valid"] is True
    assert refreshed["work_orders"]


def test_langgraph_rejection_generates_no_actions():
    graph = build_graph()
    start(graph, "graph-reject")
    rejected = graph.resume(
        thread_id="graph-reject",
        response={
            "decision": "reject",
            "actor_id": "planner_test",
            "comment": "Reject for drill review.",
        },
    )
    assert rejected["status"] == "rejected"
    assert rejected["work_orders"] == []


def test_preflight_evidence_conflict_pauses_before_tools_and_solver():
    graph = build_graph()
    waiting = graph.start(
        raw_text=(CASE / "supplier_delay_email.txt").read_text(encoding="utf-8"),
        source_ref="data/cases/mendeley_drill/evidence/manifest.json",
        replay_key="mendeley_seat_delay_email",
        thread_id="graph-evidence-conflict",
        preflight_conflicts=["delay_hours: fresh_sources_disagree"],
        preflight_required_confirmations=["authoritative_delay_hours"],
    )

    assert waiting["status"] == "needs_clarification"
    assert waiting.get("plans", []) == []
    assert waiting["incident_draft"]["conflicts"] == [
        "delay_hours: fresh_sources_disagree"
    ]
    assert waiting["incident_draft"]["required_confirmations"] == [
        "authoritative_delay_hours"
    ]
