from __future__ import annotations

import json
from pathlib import Path

import pytest

from delivery_guard.data import load_scenario
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.integration import (
    BusinessStatus,
    CanonicalCommand,
    IntegrationProfile,
    TargetSystem,
    build_commands,
    build_system_snapshots,
    run_partial_failure_demo,
)
from delivery_guard.integration.ledger import IdempotencyConflict, IntegrationLedger
from delivery_guard.integration.sandbox import ContractSandbox, callback_for
from delivery_guard.llm import ReplayLanguageModel


ROOT = Path(__file__).resolve().parents[1]


def feedback_graph() -> DeliveryGuardGraph:
    case = ROOT / "data/cases/mendeley_drill"
    return DeliveryGuardGraph(
        scenario_path=case / "scenario.json",
        knowledge_paths=[
            case / "customer_sla.md",
            case / "procurement_policy.md",
            case / "safety_policy.md",
        ],
        model=ReplayLanguageModel(ROOT / "data/model_replays/mendeley_drill.json"),
    )


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(ROOT / "data/cases/mendeley_drill/scenario.json")


@pytest.fixture(scope="module")
def approved_result():
    return json.loads((ROOT / "artifacts/public_data_graph_run.json").read_text(encoding="utf-8"))


def test_canonical_snapshots_preserve_erp_mes_boundaries(scenario):
    snapshots = build_system_snapshots(scenario)
    assert snapshots["erp"]["source_revision"] == "erp-rev-17"
    assert snapshots["mes"]["source_revision"] == "mes-rev-12"
    assert len(snapshots["erp"]["entities"]["orders"]) == 3
    assert snapshots["erp"]["content_hash"] != snapshots["mes"]["content_hash"]


def test_only_approved_graph_result_builds_commands(approved_result):
    commands = build_commands(approved_result, IntegrationProfile.KINGDEE_BLACKLAKE)
    assert {command.target_system for command in commands} == {TargetSystem.ERP, TargetSystem.MES}
    assert all(command.approval_id == "approval_006" for command in commands)
    assert all(command.environment == "sandbox" for command in commands)

    rejected = {**approved_result, "status": "rejected"}
    with pytest.raises(ValueError, match="human-approved"):
        build_commands(rejected, IntegrationProfile.KINGDEE_BLACKLAKE)


def test_device_control_command_fails_closed(approved_result):
    source = build_commands(approved_result, IntegrationProfile.SAP_S4_DM)[0]
    payload = source.model_dump(mode="json", exclude={"payload_hash"})
    payload["command_type"] = "OPC_UA_WRITE"
    with pytest.raises(ValueError, match="device control"):
        CanonicalCommand.model_validate(payload)


def test_idempotent_submit_and_conflict(approved_result, scenario):
    command = build_commands(approved_result, IntegrationProfile.SAP_S4_DM)[0]
    ledger = IntegrationLedger()
    sandbox = ContractSandbox(
        profile=IntegrationProfile.SAP_S4_DM,
        snapshots=build_system_snapshots(scenario),
        ledger=ledger,
    )
    try:
        first = sandbox.submit(command)
        second = sandbox.submit(command)
        assert first.duplicate is False
        assert second.duplicate is True
        assert first.operation_id == second.operation_id
        assert len(ledger.command_rows()) == 1

        mutated = command.model_dump(mode="json", exclude={"payload_hash"})
        mutated["payload"] = {**mutated["payload"], "tampered": True}
        conflicting = CanonicalCommand.model_validate(mutated)
        with pytest.raises(IdempotencyConflict):
            sandbox.submit(conflicting)
    finally:
        ledger.close()


def test_out_of_order_callback_does_not_regress_status(approved_result, scenario):
    command = build_commands(approved_result, IntegrationProfile.KINGDEE_BLACKLAKE)[0]
    ledger = IntegrationLedger()
    sandbox = ContractSandbox(
        profile=IntegrationProfile.KINGDEE_BLACKLAKE,
        snapshots=build_system_snapshots(scenario),
        ledger=ledger,
    )
    try:
        ack = sandbox.submit(command)
        applied = callback_for(
            command,
            ack,
            event_id="evt_applied_sequence_2",
            sequence=2,
            status=BusinessStatus.APPLIED,
            source_revision_after="erp-rev-18",
        )
        pending = callback_for(
            command,
            ack,
            event_id="evt_old_pending_sequence_1",
            sequence=1,
            status=BusinessStatus.PENDING,
            source_revision_after="erp-rev-17",
        )
        assert sandbox.receive_callback(applied).current_business_status == BusinessStatus.APPLIED
        stale = sandbox.receive_callback(pending)
        assert stale.stale_sequence is True
        assert stale.current_business_status == BusinessStatus.APPLIED
    finally:
        ledger.close()


def test_partial_failure_demo_runs_real_http_and_replans(approved_result, scenario):
    report = run_partial_failure_demo(
        scenario,
        approved_result,
        IntegrationProfile.KINGDEE_BLACKLAKE,
        feedback_graph=feedback_graph(),
        feedback_thread_id="integration-contract-feedback",
    )
    assert report["http_boundary"]["health_checked"] is True
    assert report["http_boundary"]["command_posts"] == 2
    assert report["overall_business_status"] == "PARTIALLY_APPLIED"
    assert report["plan_stale"] is True
    assert report["old_approval_reused"] is False
    assert report["replan"]["status"] == "awaiting_approval"
    assert report["replan"]["previous_approval_valid"] is False
    assert report["replan"]["work_orders"] == []
    assert report["replan"]["scenario_hash"] != report["replan"]["previous_scenario_hash"]
    assert [item["node"] for item in report["replan"]["graph_trace"]] == [
        "receive_execution_feedback",
        "invalidate_stale_approval",
        "plan_investigation",
        "execute_investigation",
        "analyze_and_solve",
    ]
    assert report["safety"]["device_control"] is False
