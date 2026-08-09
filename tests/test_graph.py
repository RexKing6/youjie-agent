from pathlib import Path

from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.llm import ReplayLanguageModel


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
