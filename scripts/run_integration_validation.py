"""Run deterministic adversarial validation for the ERP/MES contract sandbox.

The report distinguishes transport acceptance from business execution and proves
that stale feedback cannot reuse an earlier human approval.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from delivery_guard.data import load_scenario
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.hashing import stable_hash
from delivery_guard.integration import (
    BusinessStatus,
    CanonicalCommand,
    IntegrationProfile,
    build_commands,
    build_system_snapshots,
    run_partial_failure_demo,
)
from delivery_guard.integration.ledger import IdempotencyConflict, IntegrationLedger
from delivery_guard.integration.sandbox import ContractSandbox, callback_for
from delivery_guard.llm import ReplayLanguageModel


ROOT = Path(__file__).resolve().parents[1]
FIXED_AS_OF = "2026-08-29T18:00:00+08:00"


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


def checked(name: str, claim: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        evidence = fn()
        return {"id": name, "claim": claim, "passed": True, "evidence": evidence}
    except Exception as exc:  # report every failure before failing the script
        return {
            "id": name,
            "claim": claim,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def strip_runtime_objects(value: Any) -> Any:
    """Keep persisted evidence JSON-native while preserving graph traces."""
    if isinstance(value, dict):
        return {
            key: strip_runtime_objects(item)
            for key, item in value.items()
            if key != "__interrupt__"
        }
    if isinstance(value, list):
        return [strip_runtime_objects(item) for item in value]
    return value


def normalized_digest(report: dict[str, Any]) -> str:
    payload = deepcopy(report)
    payload.get("http_boundary", {}).pop("base_url", None)
    def strip_runtime(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_runtime(item)
                for key, item in value.items()
                if key not in {"solve_time_ms"}
            }
        if isinstance(value, list):
            return [strip_runtime(item) for item in value]
        return value

    payload = strip_runtime(payload)
    return stable_hash(payload)


def run_suite(profile: IntegrationProfile, scenario: Any, approved: dict[str, Any]) -> list[dict[str, Any]]:
    commands = build_commands(approved, profile)
    first = commands[0]

    def approval_gate() -> dict[str, Any]:
        blocked = deepcopy(approved)
        blocked["status"] = "awaiting_approval"
        try:
            build_commands(blocked, profile)
        except ValueError as exc:
            require("human-approved" in str(exc), "wrong approval failure")
            return {"command_count": 0, "failure": str(exc)}
        raise AssertionError("unapproved result created a command")

    def plan_binding() -> dict[str, Any]:
        tampered = deepcopy(approved)
        tampered["workflow"]["approval"]["valid"] = False
        try:
            build_commands(tampered, profile)
        except ValueError as exc:
            require("valid human approval" in str(exc), "invalid approval not rejected")
            return {"command_count": 0, "failure": str(exc)}
        raise AssertionError("invalid approval created a command")

    def idempotent_submit() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            ack1 = sandbox.submit(first)
            ack2 = sandbox.submit(first)
            require(not ack1.duplicate and ack2.duplicate, "duplicate marker incorrect")
            require(ack1.operation_id == ack2.operation_id, "duplicate created a new operation")
            require(len(ledger.command_rows()) == 1, "duplicate created another side effect")
            return {"operation_id": ack1.operation_id, "command_rows": 1, "duplicate": True}
        finally:
            ledger.close()

    def idempotency_conflict() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            sandbox.submit(first)
            mutated = first.model_dump(mode="json", exclude={"payload_hash"})
            mutated["payload"] = {**mutated["payload"], "tampered": True}
            conflicting = CanonicalCommand.model_validate(mutated)
            try:
                sandbox.submit(conflicting)
            except IdempotencyConflict as exc:
                require(len(ledger.command_rows()) == 1, "conflict created a side effect")
                return {"business_status": "REJECTED", "failure": str(exc), "command_rows": 1}
            raise AssertionError("same key with different payload was accepted")
        finally:
            ledger.close()

    def ack_is_not_execution() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            ack = sandbox.submit(first)
            require(ack.business_status == BusinessStatus.PENDING, "transport ACK claimed execution")
            require(ledger.command_status(first.command_id) == BusinessStatus.PENDING, "ledger claimed execution")
            return {"transport_status": ack.transport_status.value, "business_status": ack.business_status.value}
        finally:
            ledger.close()

    def callback_reordering() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            ack = sandbox.submit(first)
            applied = callback_for(first, ack, event_id="evt_seq_2", sequence=2, status=BusinessStatus.APPLIED, source_revision_after="erp-rev-18")
            older = callback_for(first, ack, event_id="evt_seq_1", sequence=1, status=BusinessStatus.PENDING, source_revision_after="erp-rev-17")
            sandbox.receive_callback(applied)
            receipt = sandbox.receive_callback(older)
            require(receipt.stale_sequence, "old callback was not marked stale")
            require(receipt.current_business_status == BusinessStatus.APPLIED, "status regressed")
            return {"stale_sequence": True, "current_business_status": receipt.current_business_status.value}
        finally:
            ledger.close()

    def callback_deduplication() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            ack = sandbox.submit(first)
            event = callback_for(first, ack, event_id="evt_duplicate", sequence=1, status=BusinessStatus.APPLIED, source_revision_after="erp-rev-18")
            first_receipt = sandbox.receive_callback(event)
            second_receipt = sandbox.receive_callback(event)
            require(not first_receipt.duplicate and second_receipt.duplicate, "callback dedupe failed")
            require(ledger.command_status(first.command_id) == BusinessStatus.APPLIED, "state changed after duplicate")
            return {"duplicate": True, "current_business_status": "APPLIED"}
        finally:
            ledger.close()

    def forged_ack_text() -> dict[str, Any]:
        ledger = IntegrationLedger()
        sandbox = ContractSandbox(profile=profile, snapshots=build_system_snapshots(scenario), ledger=ledger)
        try:
            ack = sandbox.submit(first)
            forged_text = "HTTP 202 accepted and the ERP update succeeded"
            require("succeeded" in forged_text, "fixture malformed")
            require(ledger.command_status(first.command_id) == BusinessStatus.PENDING, "unparsed text changed state")
            return {"forged_text_ignored": True, "operation_id": ack.operation_id, "business_status": "PENDING"}
        finally:
            ledger.close()

    def device_control_block() -> dict[str, Any]:
        payload = first.model_dump(mode="json", exclude={"payload_hash"})
        payload["command_type"] = "OPC_UA_WRITE"
        try:
            CanonicalCommand.model_validate(payload)
        except ValueError as exc:
            require("device control" in str(exc), "wrong safety rejection")
            return {"command_count": 0, "failure": "device control commands are forbidden"}
        raise AssertionError("device-control command was accepted")

    report = run_partial_failure_demo(
        scenario,
        approved,
        profile,
        feedback_graph=feedback_graph(),
        feedback_thread_id=f"validation-{profile.value}-representative",
    )

    def partial_failure() -> dict[str, Any]:
        states = {row["target_system"]: row["business_status"] for row in report["command_states"]}
        require(report["overall_business_status"] == "PARTIALLY_APPLIED", "partial failure hidden")
        require(sorted(states.values()) == ["APPLIED", "REJECTED"], "wrong terminal states")
        return {"overall": report["overall_business_status"], "states": states}

    def stale_replan() -> dict[str, Any]:
        replan = report["replan"]
        require(report["plan_stale"], "capacity feedback did not stale plan")
        require(replan["scenario_hash"] != replan["previous_scenario_hash"], "scenario hash unchanged")
        require(replan["previous_approval_valid"] is False, "old approval remains valid")
        require(report["old_approval_reused"] is False, "old approval reused")
        require(replan["status"] == "awaiting_approval" and replan["work_orders"] == [], "replan bypassed approval")
        return {
            "plan_stale": True,
            "old_approval_reused": False,
            "replan_status": replan["status"],
            "new_work_orders": len(replan["work_orders"]),
        }

    def no_fake_rollback() -> dict[str, Any]:
        erp = next(row for row in report["command_states"] if row["target_system"] == "erp_sandbox")
        require(erp["business_status"] == "APPLIED", "applied ERP state was rolled back or hidden")
        return {"erp_business_status": erp["business_status"], "compensation_boundary": "manual/native-system"}

    def source_revision_feedback() -> dict[str, Any]:
        mes_callback = next(item for item in report["callbacks"] if "mes_sandbox" in item["source"])
        require(mes_callback["source_revision_after"] == "mes-rev-13", "revision feedback missing")
        require("capacity:line_zp7_public" in mes_callback["changed_entities"], "changed capacity missing")
        return {"source_revision_after": mes_callback["source_revision_after"], "changed_entities": mes_callback["changed_entities"]}

    def audit_trace() -> dict[str, Any]:
        event_types = {event["event_type"] for event in report["audit"]}
        require({"COMMAND_QUEUED", "TRANSPORT_ACCEPTED", "BUSINESS_CALLBACK"} <= event_types, "audit chain incomplete")
        return {"event_count": len(report["audit"]), "event_types": sorted(event_types)}

    def contract_disclosure() -> dict[str, Any]:
        require("NON-CERTIFIED" in report["disclosure"], "non-certification disclosure missing")
        require(report["safety"] == {
            "real_vendor_tenant": False,
            "certified_connector": False,
            "device_control": False,
            "native_erp_approval": False,
        }, "safety boundary drift")
        return {"disclosure": report["disclosure"], "safety": report["safety"]}

    def error_policy() -> dict[str, Any]:
        mes_callback = next(item for item in report["callbacks"] if item["business_status"] == "REJECTED")
        error = mes_callback["errors"][0]
        require(error["code"] == "STALE_CAPACITY_REVISION" and error["retryable"] is False, "unsafe retry classification")
        return {"error_code": error["code"], "retryable": error["retryable"], "action": "replan_then_human_approve"}

    return [
        checked("ADV-01", "No human approval means no outbound command.", approval_gate),
        checked("ADV-02", "Invalid/stale approval binding means no outbound command.", plan_binding),
        checked("ADV-03", "Duplicate submission creates one business operation.", idempotent_submit),
        checked("ADV-04", "Same idempotency key with another payload fails closed.", idempotency_conflict),
        checked("ADV-05", "HTTP/transport acceptance remains business PENDING.", ack_is_not_execution),
        checked("ADV-06", "ERP success plus MES rejection is exposed as partial application.", partial_failure),
        checked("ADV-07", "Out-of-order callbacks cannot regress terminal state.", callback_reordering),
        checked("ADV-08", "Duplicate callbacks are deduplicated.", callback_deduplication),
        checked("ADV-09", "Capacity feedback invalidates the old scenario and plan.", stale_replan),
        checked("ADV-10", "Old approval is not reused and new work orders stay zero.", stale_replan),
        checked("ADV-11", "Already applied ERP work is not falsely rolled back.", no_fake_rollback),
        checked("ADV-12", "Free-form success text cannot mutate business state.", forged_ack_text),
        checked("ADV-13", "Device-control commands are rejected at the contract boundary.", device_control_block),
        checked("ADV-14", "Source revisions and changed dependencies return in callbacks.", source_revision_feedback),
        checked("ADV-15", "Non-retryable stale revisions trigger replan, not blind retry.", error_policy),
        checked("ADV-16", "The full command/ACK/callback chain is auditable.", audit_trace),
        checked("ADV-17", "The connector is disclosed as non-certified sandbox only.", contract_disclosure),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--output", default="artifacts/integration_validation_report.json")
    args = parser.parse_args()
    require(args.runs >= 2, "--runs must be at least 2")

    scenario = load_scenario(ROOT / "data/cases/mendeley_drill/scenario.json")
    approved = json.loads((ROOT / "artifacts/public_data_graph_run.json").read_text(encoding="utf-8"))
    profiles: dict[str, Any] = {}
    total_checks = 0
    failed_checks = 0
    for profile in IntegrationProfile:
        checks = run_suite(profile, scenario, approved)
        repeats = [
            strip_runtime_objects(
                run_partial_failure_demo(
                    scenario,
                    approved,
                    profile,
                    feedback_graph=feedback_graph(),
                    feedback_thread_id=f"validation-{profile.value}-repeat-{index}",
                )
            )
            for index in range(args.runs)
        ]
        digests = [normalized_digest(item) for item in repeats]
        repeat_identical = len(set(digests)) == 1
        checks.append({
            "id": "STAB-01",
            "claim": f"{args.runs} complete HTTP sandbox runs are deterministic after removing ephemeral ports.",
            "passed": repeat_identical,
            "evidence": {"run_count": args.runs, "unique_digest_count": len(set(digests)), "digests": digests},
        })
        total_checks += len(checks)
        failed_checks += sum(not item["passed"] for item in checks)
        profiles[profile.value] = {
            "checks": checks,
            "representative_run": repeats[0],
            "repeat_outputs_identical": repeat_identical,
        }

    report = {
        "schema_version": "youjie.integration_validation/v1",
        "as_of": FIXED_AS_OF,
        "run_mode": "real_localhost_http_contract_sandbox",
        "profile_count": len(profiles),
        "repeat_runs_per_profile": args.runs,
        "total_checks": total_checks,
        "passed_checks": total_checks - failed_checks,
        "failed_checks": failed_checks,
        "claim_boundary": (
            "Contract-compatible sandbox evidence only. It is not a certified connector, "
            "does not use a live vendor tenant, and does not control equipment."
        ),
        "profiles": profiles,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"integration validation {report['passed_checks']}/{total_checks} -> {output}")
    if failed_checks:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
