"""Build commands, run the HTTP sandbox, reconcile feedback, and re-plan safely."""

from __future__ import annotations

from typing import Any

from delivery_guard.data import apply_incident
from delivery_guard.diagnostics import summarize_plan
from delivery_guard.hashing import stable_hash
from delivery_guard.integration.contracts import (
    BusinessStatus,
    CanonicalCommand,
    IntegrationProfile,
    TargetSystem,
)
from delivery_guard.integration.ledger import IntegrationLedger
from delivery_guard.integration.sandbox import (
    ContractSandbox,
    SandboxHttpClient,
    SandboxHttpService,
    callback_for,
)
from delivery_guard.models import Incident, IncidentKind, Scenario
from delivery_guard.workflow import RecoveryWorkflow


DEFAULT_TIME = "2026-08-29T10:20:30+08:00"


def build_system_snapshots(scenario: Scenario) -> dict[str, dict[str, Any]]:
    common = {
        "schema_version": "youjie.canonical/v1",
        "scenario_id": scenario.scenario_id,
        "environment": "sandbox",
        "as_of": scenario.provenance.as_of,
        "disclosure": "Synthetic/public-derived contract sandbox; no live vendor tenant.",
    }
    erp_entities = {
        "orders": [item.model_dump(mode="json") for item in scenario.orders],
        "bom": [item.model_dump(mode="json") for item in scenario.bom],
        "inventory": [item.model_dump(mode="json") for item in scenario.inventory],
        "supplier_commitments": [
            item.model_dump(mode="json") for item in scenario.supplier_sources
        ],
    }
    mes_entities = {
        "production_lines": [
            item.model_dump(mode="json") for item in scenario.production_lines
        ],
        "routing": [
            item.model_dump(mode="json") for item in scenario.route_operations
        ],
    }
    return {
        "erp": {
            **common,
            "source_system": "erp_sandbox",
            "source_revision": "erp-rev-17",
            "entities": erp_entities,
            "content_hash": stable_hash(erp_entities),
        },
        "mes": {
            **common,
            "source_system": "mes_sandbox",
            "source_revision": "mes-rev-12",
            "entities": mes_entities,
            "content_hash": stable_hash(mes_entities),
        },
    }


def _command(
    *,
    profile: IntegrationProfile,
    target: TargetSystem,
    command_type: str,
    correlation_id: str,
    causation_id: str,
    scenario_hash: str,
    plan_hash: str,
    approval_id: str,
    expected_source_revision: str,
    payload: dict[str, Any],
    created_at: str,
) -> CanonicalCommand:
    identity = stable_hash({
        "profile": profile.value,
        "target": target.value,
        "command_type": command_type,
        "plan_hash": plan_hash,
        "approval_id": approval_id,
        "payload": payload,
    })
    return CanonicalCommand(
        command_id=f"cmd_{identity[:16]}",
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key=f"sha256:{identity}",
        profile=profile,
        target_system=target,
        command_type=command_type,
        scenario_hash=scenario_hash,
        plan_hash=plan_hash,
        approval_id=approval_id,
        expected_source_revision=expected_source_revision,
        created_at=created_at,
        payload=payload,
    )


def build_commands(
    graph_result: dict[str, Any],
    profile: IntegrationProfile,
    *,
    created_at: str = DEFAULT_TIME,
) -> list[CanonicalCommand]:
    if graph_result.get("status") != "completed":
        raise ValueError("only a completed, human-approved graph result may create commands")
    workflow = graph_result.get("workflow") or {}
    approval = workflow.get("approval") or {}
    if approval.get("decision") != "approve" or approval.get("valid") is not True:
        raise ValueError("a valid human approval is required")
    scenario_hash = workflow.get("scenario_hash")
    plan_hash = approval.get("plan_hash")
    approval_id = approval.get("approval_id")
    if not scenario_hash or not plan_hash or not approval_id:
        raise ValueError("approval must bind scenario_hash, plan_hash, and approval_id")
    work_orders = graph_result.get("work_orders") or []
    if not work_orders:
        raise ValueError("no draft work orders available")
    correlation_id = f"cor_{stable_hash({'scenario': scenario_hash, 'plan': plan_hash, 'approval': approval_id})[:16]}"

    purchases = [
        item for item in work_orders if item["work_order_type"] == "supplier_purchase_request"
    ]
    schedules = [
        item for item in work_orders if item["work_order_type"] == "schedule_change_order"
    ]
    risks = [
        item for item in work_orders if item["work_order_type"] == "customer_communication_task"
    ]
    commands: list[CanonicalCommand] = []
    if purchases or risks:
        commands.append(_command(
            profile=profile,
            target=TargetSystem.ERP,
            command_type="CREATE_PURCHASE_REQUISITION_AND_ORDER_RISK_DRAFTS",
            correlation_id=correlation_id,
            causation_id=approval["plan_id"],
            scenario_hash=scenario_hash,
            plan_hash=plan_hash,
            approval_id=approval_id,
            expected_source_revision="erp-rev-17",
            payload={
                "purchase_requisition_drafts": [item["payload"] for item in purchases],
                "order_risk_update_drafts": [item["payload"] for item in risks],
                "native_workflow_boundary": "create_or_submit_draft_only; native audit/approve forbidden",
            },
            created_at=created_at,
        ))
    if schedules:
        commands.append(_command(
            profile=profile,
            target=TargetSystem.MES,
            command_type="CREATE_SCHEDULE_CHANGE_DRAFT",
            correlation_id=correlation_id,
            causation_id=approval["plan_id"],
            scenario_hash=scenario_hash,
            plan_hash=plan_hash,
            approval_id=approval_id,
            expected_source_revision="mes-rev-12",
            payload={
                "schedule_change_drafts": [item["payload"] for item in schedules],
                "device_control": False,
            },
            created_at=created_at,
        ))
    if not commands:
        raise ValueError("no supported ERP/MES commands could be built")
    return commands


def replan_after_capacity_feedback(
    scenario: Scenario,
    graph_result: dict[str, Any],
    *,
    line_id: str = "line_zp7_public",
    start_hour: int = 48,
    end_hour: int = 68,
    feedback_graph: Any | None = None,
    thread_id: str = "integration-feedback-replan",
) -> dict[str, Any]:
    original_payload = (graph_result.get("workflow") or {}).get("incident") or graph_result.get("incident")
    if not original_payload:
        raise ValueError("original incident is required for feedback re-plan")
    original_incident = Incident.model_validate(original_payload)
    compounded_base = apply_incident(scenario, original_incident)
    feedback_incident = Incident(
        incident_id="inc_mes_feedback_line_outage",
        kind=IncidentKind.LINE_OUTAGE,
        target_id=line_id,
        description=(
            "MES sandbox callback reports a newly confirmed line outage. "
            "This is synthetic feedback and cannot control equipment."
        ),
        start_hour=start_hour,
        end_hour=end_hour,
        source_type="mes_sandbox_callback",
        source_ref="/youjie/v1/callbacks",
    )
    if feedback_graph is not None:
        replanned = feedback_graph.start_feedback(
            previous_graph_result=graph_result,
            feedback_incident=feedback_incident,
            source_revision_before="mes-rev-12",
            source_revision_after="mes-rev-13",
            source_system="mes_sandbox",
            thread_id=thread_id,
        )
        return {
            **replanned,
            "reason": "MES capacity revision changed; previous approval is stale.",
        }
    workflow = RecoveryWorkflow(compounded_base, feedback_incident)
    workflow.analyze()
    workflow.solve()
    summaries = {
        plan.profile: summarize_plan(workflow.adjusted_scenario, plan)
        for plan in workflow.plans
    }
    previous_approval = (graph_result.get("workflow") or {}).get("approval") or {}
    return {
        "status": "awaiting_approval",
        "reason": "MES capacity revision changed; previous approval is stale.",
        "previous_scenario_hash": (graph_result.get("workflow") or {}).get("scenario_hash"),
        "previous_plan_hash": previous_approval.get("plan_hash"),
        "previous_approval_id": previous_approval.get("approval_id"),
        "previous_approval_valid": False,
        "scenario_hash": workflow.scenario_hash,
        "incident": feedback_incident.model_dump(mode="json"),
        "impact": workflow.impact.model_dump(mode="json"),
        "plans": [plan.model_dump(mode="json") for plan in workflow.plans],
        "plan_summaries": summaries,
        "work_orders": [],
        # Compatibility path for callers that intentionally do not provide a
        # DeliveryGuardGraph.  Do not label this deterministic recomputation as
        # a graph trace; the UI and validation suite inject the real graph.
        "replan_mode": "deterministic_fallback_without_langgraph",
        "graph_trace": [],
    }


def run_partial_failure_demo(
    scenario: Scenario,
    graph_result: dict[str, Any],
    profile: IntegrationProfile,
    *,
    feedback_graph: Any | None = None,
    feedback_thread_id: str = "integration-feedback-replan",
) -> dict[str, Any]:
    snapshots = build_system_snapshots(scenario)
    ledger = IntegrationLedger()
    sandbox = ContractSandbox(profile=profile, snapshots=snapshots, ledger=ledger)
    service = SandboxHttpService(sandbox).start()
    client = SandboxHttpClient(service.base_url)
    try:
        health = client.health()
        erp_snapshot = client.snapshot("erp", scenario.scenario_id)
        mes_snapshot = client.snapshot("mes", scenario.scenario_id)
        commands = build_commands(graph_result, profile)
        acks = []
        receipts = []
        callbacks = []
        for command in commands:
            http_status, ack_or_error = client.submit(command)
            if http_status != 202:
                raise RuntimeError(f"sandbox rejected command: {ack_or_error}")
            ack = ack_or_error
            acks.append(ack)
            if command.target_system == TargetSystem.ERP:
                callback = callback_for(
                    command,
                    ack,
                    event_id=f"evt_{stable_hash({'erp': command.command_id})[:16]}",
                    sequence=1,
                    status=BusinessStatus.APPLIED,
                    source_revision_after="erp-rev-18",
                    target_record_ids=["PR-SANDBOX-00017"],
                )
            else:
                callback = callback_for(
                    command,
                    ack,
                    event_id=f"evt_{stable_hash({'mes': command.command_id})[:16]}",
                    sequence=1,
                    status=BusinessStatus.REJECTED,
                    source_revision_after="mes-rev-13",
                    changed_entities=["capacity:line_zp7_public"],
                    error_code="STALE_CAPACITY_REVISION",
                )
            callback_status, receipt_or_error = client.callback(callback)
            if callback_status != 200:
                raise RuntimeError(f"sandbox rejected callback: {receipt_or_error}")
            callbacks.append(callback)
            receipts.append(receipt_or_error)

        command_rows = ledger.command_rows()
        statuses = [BusinessStatus(row["business_status"]) for row in command_rows]
        overall = (
            BusinessStatus.APPLIED
            if statuses and all(status == BusinessStatus.APPLIED for status in statuses)
            else BusinessStatus.PARTIALLY_APPLIED
        )
        plan_stale = any(receipt.plan_stale for receipt in receipts)
        replan = (
            replan_after_capacity_feedback(
                scenario,
                graph_result,
                feedback_graph=feedback_graph,
                thread_id=feedback_thread_id,
            )
            if plan_stale
            else None
        )
        correlation_id = commands[0].correlation_id
        return {
            "schema_version": "youjie.integration_demo/v1",
            "profile": profile.value,
            "disclosure": health["capability"]["disclosure"],
            "http_boundary": {
                "base_url": service.base_url,
                "health_checked": True,
                "snapshot_gets": 2,
                "command_posts": len(commands),
                "callback_posts": len(callbacks),
            },
            "snapshot_evidence": {
                "erp_revision": erp_snapshot["source_revision"],
                "erp_hash": erp_snapshot["content_hash"],
                "mes_revision": mes_snapshot["source_revision"],
                "mes_hash": mes_snapshot["content_hash"],
            },
            "commands": [item.model_dump(mode="json") for item in commands],
            "transport_acks": [item.model_dump(mode="json") for item in acks],
            "callbacks": [item.model_dump(mode="json") for item in callbacks],
            "callback_receipts": [item.model_dump(mode="json") for item in receipts],
            "command_states": command_rows,
            "overall_business_status": overall.value,
            "plan_stale": plan_stale,
            "old_approval_reused": False,
            "audit": client.audit(correlation_id),
            "replan": replan,
            "safety": {
                "real_vendor_tenant": False,
                "certified_connector": False,
                "device_control": False,
                "native_erp_approval": False,
            },
        }
    finally:
        service.close()
        ledger.close()
