"""Reproducible CLI for demo runs and adversarial evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from delivery_guard.adversary import evaluate_suite
from delivery_guard.agent import DeliveryGuardAgent
from delivery_guard.chaos_agent import ChaosDrillAgent
from delivery_guard.context import RecoveryAuthorization
from delivery_guard.data import load_incident, load_scenario
from delivery_guard.diagnostics import diagnose_product_request
from delivery_guard.evaluation import evaluate_agent_cases
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.llm import ReplayLanguageModel
from delivery_guard.workflow import RecoveryWorkflow


def write_json(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def command_run(args: argparse.Namespace) -> int:
    workflow = RecoveryWorkflow(load_scenario(args.scenario), load_incident(args.incident))
    workflow.analyze()
    workflow.solve()
    verified = workflow.verified_plans()
    if verified:
        chosen = next(
            (plan for plan in verified if plan.profile == args.profile),
            verified[0],
        )
        workflow.approve(
            chosen.plan_id,
            actor_id="cli_demo_operator",
            comment="Explicit approval for deterministic offline demo artifact",
        )
        workflow.generate_orders()
    payload = workflow.export()
    write_json(args.output, payload)
    print(
        json.dumps(
            {
                "state": workflow.state.value,
                "scenario_hash": workflow.scenario_hash,
                "affected_orders": len(workflow.impact.affected_orders),
                "verified_plans": len(verified),
                "work_orders": len(workflow.work_orders),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if verified else 2


def command_evaluate(args: argparse.Namespace) -> int:
    report = evaluate_suite(args.scenario, args.suite)
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "passed": report["passed_cases"],
                "failed": report["failed_cases"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["failed_cases"] == 0 else 1


def command_agent_run(args: argparse.Namespace) -> int:
    case_dir = Path(args.case_dir)
    agent = DeliveryGuardAgent(
        scenario_path=case_dir / "scenario.json",
        knowledge_paths=[
            case_dir / "customer_sla.md",
            case_dir / "procurement_policy.md",
            case_dir / "overtime_policy.md",
        ],
        model=ReplayLanguageModel(args.replay),
    )
    email_path = case_dir / "supplier_delay_email.txt"
    agent.ingest(
        email_path.read_text(encoding="utf-8"),
        source_ref=str(email_path),
        replay_key="delivery_crisis_email",
    )
    agent.authorize_and_solve(
        RecoveryAuthorization(
            allow_beta=True,
            beta_max_quantity=args.beta_max,
            allow_overtime=True,
            overtime_max_units=args.overtime_max,
            actor_id="cli_demo_planner",
            comment="Explicit CLI authorization envelope",
        )
    )
    agent.approve(
        args.profile,
        actor_id="cli_demo_planner",
        comment="Approve draft-only competition artifact",
    )
    payload = agent.export()
    write_json(args.output, payload)
    summary = payload["plan_summaries"][args.profile]
    print(
        json.dumps(
            {
                "agent_state": payload["context"]["state"],
                "model_mode": payload["context"]["model_mode"],
                "profile": args.profile,
                "first_due_on_time_units": summary["first_due_on_time_units"],
                "first_due_late_units": summary["first_due_late_units"],
                "recovery_cost": summary["recovery_cost"],
                "tool_calls": len(payload["context"]["tool_traces"]),
                "draft_actions": len(payload["workflow"]["work_orders"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_agent_evaluate(args: argparse.Namespace) -> int:
    first = evaluate_agent_cases(args.cases, ReplayLanguageModel(args.replay))
    second = evaluate_agent_cases(args.cases, ReplayLanguageModel(args.replay))
    first_decisions = [item["actual"] for item in first["results"]]
    second_decisions = [item["actual"] for item in second["results"]]
    first["repeated_runs"] = 2
    first["repeat_outputs_identical"] = first_decisions == second_decisions
    first["metrics"]["deterministic_repeat_rate"] = (
        1.0 if first["repeat_outputs_identical"] else 0.0
    )
    write_json(args.output, first)
    print(
        json.dumps(
            {
                "mode": first["evaluation_mode"],
                "model": first["model_name"],
                "passed": first["passed_cases"],
                "failed": first["failed_cases"],
                "repeat_outputs_identical": first["repeat_outputs_identical"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if first["failed_cases"] == 0 and first["repeat_outputs_identical"] else 1


def command_diagnose_request(args: argparse.Namespace) -> int:
    workflow = RecoveryWorkflow(load_scenario(args.scenario), load_incident(args.incident))
    workflow.analyze()
    report = diagnose_product_request(
        workflow.adjusted_scenario,
        product_id=args.product,
        requested_total_units=args.requested_units,
        due_hour=args.due_hour,
    )
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "feasible_by_due": report["feasible_by_due"],
                "maximum_by_due": report["maximum_deliverable_by_due"],
                "maximum_within_horizon": report["maximum_deliverable_within_horizon"],
                "alternatives": len(report["alternatives"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _public_graph(case_dir: Path, replay: str | Path) -> DeliveryGuardGraph:
    return DeliveryGuardGraph(
        scenario_path=case_dir / "scenario.json",
        knowledge_paths=[
            case_dir / "customer_sla.md",
            case_dir / "procurement_policy.md",
            case_dir / "safety_policy.md",
        ],
        model=ReplayLanguageModel(replay),
    )


def command_run_graph(args: argparse.Namespace) -> int:
    case_dir = Path(args.case_dir)
    graph = _public_graph(case_dir, args.replay)
    source = case_dir / "supplier_delay_email.txt"
    waiting = graph.start(
        raw_text=source.read_text(encoding="utf-8"),
        source_ref=str(source),
        replay_key="mendeley_seat_delay_email",
        thread_id=args.thread_id,
    )
    result = graph.resume(
        thread_id=args.thread_id,
        response={
            "decision": "approve",
            "profile": args.profile,
            "actor_id": "cli_public_data_planner",
            "comment": "Approve draft-only actions in the isolated public-data drill.",
        },
    )
    result["run_metadata"] = {
        "orchestrator": "LangGraph",
        "model_mode": "replay",
        "human_interrupt_observed": bool(waiting.get("__interrupt__")),
        "scenario_source": str(case_dir / "scenario.json"),
    }
    write_json(args.output, result)
    print(json.dumps({
        "status": result["status"],
        "orchestrator": "LangGraph",
        "human_interrupt_observed": result["run_metadata"]["human_interrupt_observed"],
        "draft_actions": len(result["work_orders"]),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


def command_run_drill(args: argparse.Namespace) -> int:
    case_dir = Path(args.case_dir)
    scenario = load_scenario(case_dir / "scenario.json")
    drill = ChaosDrillAgent().generate(scenario, args.seed)
    graph = _public_graph(case_dir, args.replay)
    waiting = graph.start_drill(drill=drill, thread_id=args.thread_id)
    verified = [plan["profile"] for plan in waiting["plans"] if plan.get("evidence", {}).get("verified")]
    if verified:
        profile = args.profile if args.profile in verified else verified[0]
        response = {
            "decision": "approve",
            "profile": profile,
            "actor_id": "cli_chaos_drill_planner",
            "comment": "Approve draft-only actions for a seeded synthetic resilience drill.",
        }
    else:
        response = {
            "decision": "reject",
            "actor_id": "cli_chaos_drill_planner",
            "comment": "No verified plan exists; reject and generate no actions.",
        }
    result = graph.resume(thread_id=args.thread_id, response=response)
    result["drill"] = drill.model_dump(mode="json")
    result["run_metadata"] = {
        "orchestrator": "LangGraph",
        "generator": "ChaosDrillAgent",
        "seed": args.seed,
        "human_interrupt_observed": bool(waiting.get("__interrupt__")),
    }
    write_json(args.output, result)
    print(json.dumps({
        "status": result["status"],
        "incident_kind": drill.incident.kind.value,
        "seed": args.seed,
        "draft_actions": len(result["work_orders"]),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youjie")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one complete incident workflow")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--incident", required=True)
    run_parser.add_argument("--profile", default="balanced")
    run_parser.add_argument("--output", required=True)
    run_parser.set_defaults(handler=command_run)

    evaluate_parser = subparsers.add_parser("evaluate", help="Run adversarial suite")
    evaluate_parser.add_argument("--scenario", required=True)
    evaluate_parser.add_argument("--suite", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.set_defaults(handler=command_evaluate)

    agent_parser = subparsers.add_parser(
        "run-agent",
        help="Run the complete replay Agent case with explicit authorization",
    )
    agent_parser.add_argument("--case-dir", required=True)
    agent_parser.add_argument("--replay", required=True)
    agent_parser.add_argument("--profile", default="balanced")
    agent_parser.add_argument("--beta-max", type=int, default=80)
    agent_parser.add_argument("--overtime-max", type=int, default=20)
    agent_parser.add_argument("--output", required=True)
    agent_parser.set_defaults(handler=command_agent_run)

    agent_eval_parser = subparsers.add_parser(
        "evaluate-agent",
        help="Evaluate 30 versioned Agent decisions using replay evidence",
    )
    agent_eval_parser.add_argument("--cases", required=True)
    agent_eval_parser.add_argument("--replay", required=True)
    agent_eval_parser.add_argument("--output", required=True)
    agent_eval_parser.set_defaults(handler=command_agent_evaluate)

    diagnostic_parser = subparsers.add_parser(
        "diagnose-request",
        help="Compute deterministic upper bounds for an impossible product request",
    )
    diagnostic_parser.add_argument("--scenario", required=True)
    diagnostic_parser.add_argument("--incident", required=True)
    diagnostic_parser.add_argument("--product", required=True)
    diagnostic_parser.add_argument("--requested-units", required=True, type=int)
    diagnostic_parser.add_argument("--due-hour", required=True, type=int)
    diagnostic_parser.add_argument("--output", required=True)
    diagnostic_parser.set_defaults(handler=command_diagnose_request)

    graph_parser = subparsers.add_parser(
        "run-graph",
        help="Run the Mendeley public-data case through LangGraph and a real approval interrupt",
    )
    graph_parser.add_argument("--case-dir", required=True)
    graph_parser.add_argument("--replay", required=True)
    graph_parser.add_argument("--profile", default="balanced")
    graph_parser.add_argument("--thread-id", default="cli-public-data-run")
    graph_parser.add_argument("--output", required=True)
    graph_parser.set_defaults(handler=command_run_graph)

    drill_parser = subparsers.add_parser(
        "run-drill",
        help="Generate one seeded bounded incident and run it through LangGraph",
    )
    drill_parser.add_argument("--case-dir", required=True)
    drill_parser.add_argument("--replay", required=True)
    drill_parser.add_argument("--seed", type=int, default=20260810)
    drill_parser.add_argument("--profile", default="balanced")
    drill_parser.add_argument("--thread-id", default="cli-chaos-drill-run")
    drill_parser.add_argument("--output", required=True)
    drill_parser.set_defaults(handler=command_run_drill)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
