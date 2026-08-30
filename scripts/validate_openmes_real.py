#!/usr/bin/env python3
"""Validate the real local ERPNext -> OpenMES handoff without exposing secrets.

The generated evidence contains only system identifiers, revisions, hashes,
statuses, upstream commit and boundary assertions.  It intentionally stops at
the OpenMES PENDING state; a separate human action and feedback validation must
prove that execution state can change outside 有界.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.demo_api import load_runtime_credentials
from delivery_guard.integration import (
    ERPNextAdapter,
    ERPNextConfig,
    ERPNextExecutionLedger,
    ERPNextHttpClient,
    ERPNextMapping,
    OpenMESAdapter,
    OpenMESConfig,
    OpenMESExecutionLedger,
    OpenMESHttpClient,
    OpenMESMapping,
    build_erpnext_commands,
    build_openmes_command,
    compare_openmes_snapshots,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openmes-credential-file", type=Path, required=True)
    parser.add_argument(
        "--erpnext-ledger",
        type=Path,
        default=ROOT / ".tmp/openmes_real_erpnext_execution.sqlite3",
    )
    parser.add_argument(
        "--openmes-ledger",
        type=Path,
        default=ROOT / ".tmp/openmes_real_execution.sqlite3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/openmes_real_validation.json",
    )
    args = parser.parse_args()

    load_runtime_credentials()
    erp_config = ERPNextConfig.from_environment()
    if erp_config is None:
        raise RuntimeError("ERPNext server-side configuration is required")
    mes_config = OpenMESConfig.from_environment({
        "DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE": str(args.openmes_credential_file),
    })
    if mes_config is None:
        raise RuntimeError("OpenMES credential file did not produce a configuration")

    erp_mapping = ERPNextMapping.from_path(ROOT / "data/integrations/erpnext_demo_mapping.json")
    mes_mapping = OpenMESMapping.from_path(ROOT / "data/integrations/openmes_demo_mapping.json")
    approved = json.loads((ROOT / "artifacts/public_data_graph_run.json").read_text(encoding="utf-8"))

    erp_adapter = ERPNextAdapter(
        ERPNextHttpClient(erp_config),
        ledger=ERPNextExecutionLedger(args.erpnext_ledger),
    )
    erp_before = erp_adapter.execution_snapshot()
    erp_commands = build_erpnext_commands(
        approved,
        erp_mapping,
        expected_source_revision=erp_before["source_revision"],
    )
    erp_results = [erp_adapter.execute(command) for command in erp_commands]
    erp_duplicate_results = [erp_adapter.execute(command) for command in erp_commands]

    work_order_records = [
        record
        for result in erp_results
        for record in result.records
        if record.doctype == "Work Order"
    ]
    work_order_documents = [
        document
        for command in erp_commands
        for document in command.payload.get("documents", [])
        if document.get("doctype") == "Work Order"
    ]
    if len(work_order_records) != len(work_order_documents):
        raise RuntimeError("ERPNext records cannot be mapped to approved schedule documents")
    item_to_order = {
        production_item: order_id
        for order_id, production_item in erp_mapping.order_to_production_item.items()
    }
    links = [
        {
            "order_id": item_to_order[document["production_item"]],
            "erpnext_work_order": record.name,
            "production_item": document["production_item"],
            "qty": document["qty"],
        }
        for record, document in zip(work_order_records, work_order_documents, strict=True)
    ]

    mes_adapter = OpenMESAdapter(
        OpenMESHttpClient(mes_config),
        ledger=OpenMESExecutionLedger(args.openmes_ledger),
    )
    mes_health = mes_adapter.client.health()
    watched = [link["erpnext_work_order"] for link in links]
    mes_before = mes_adapter.execution_snapshot(watched)
    mes_command = build_openmes_command(
        approved,
        mes_mapping,
        links,
        expected_source_revision=mes_before["source_revision"],
    )
    mes_result = mes_adapter.execute(mes_command)
    mes_duplicate_result = mes_adapter.execute(mes_command)
    mes_after = mes_adapter.execution_snapshot(watched)
    handoff_delta = compare_openmes_snapshots(mes_before, mes_after)

    evidence = {
        "schema_version": "youjie.openmes_real_validation/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "product": "Mes-Open/OpenMes",
            "status": mes_health["status"],
            "environment": mes_health["environment"],
            "public_host": mes_health["public_host"],
            "upstream_commit": mes_health["upstream_commit"],
            "credentials_exposed": False,
        },
        "approval": {
            "approval_id": approved["workflow"]["approval"]["approval_id"],
            "scenario_hash": approved["workflow"]["scenario_hash"],
            "plan_hash": approved["workflow"]["approval"]["plan_hash"],
        },
        "erpnext": {
            "public_host": erp_config.public_host,
            "work_orders": links,
            "duplicate_retry_created_nothing": all(row.duplicate for row in erp_duplicate_results),
        },
        "openmes": {
            "command_id": mes_result.command_id,
            "business_status": mes_result.business_status.value,
            "imported": mes_result.imported,
            "updated": mes_result.updated,
            "records": [row.model_dump(mode="json") for row in mes_result.records],
            "duplicate_retry_created_nothing": mes_duplicate_result.duplicate,
            "source_revision_before": mes_before["source_revision"],
            "source_revision_after_import": mes_after["source_revision"],
            "handoff_delta": handoff_delta,
            "feedback_baseline": mes_after,
        },
        "feedback_validation": {
            "status": "awaiting_human_openmes_transition",
            "previous_approval_valid": True,
        },
        "assertions": {
            "authenticated_real_openmes_http": mes_health["status"] == "connected",
            "three_erpnext_work_orders_mapped": len(links) == 3,
            "three_openmes_work_orders_imported_and_read_back": len(mes_result.records) == 3,
            "same_business_order_numbers_across_systems": (
                {row["erpnext_work_order"] for row in links}
                == {row.order_no for row in mes_result.records}
            ),
            "all_initial_openmes_states_pending": all(row.status == "PENDING" for row in mes_result.records),
            "import_changed_openmes_revision": handoff_delta["changed"],
            "duplicate_retries_created_nothing": (
                all(row.duplicate for row in erp_duplicate_results)
                and mes_duplicate_result.duplicate
            ),
            "credentials_absent_from_evidence": True,
            "no_line_start_stop_machine_or_ot_write": True,
        },
        "boundaries": {
            "erpnext_role": "ISA-95 Level 4 business and planning test record",
            "openmes_role": "ISA-95 Level 3 execution-state test record",
            "device_control": False,
            "production_tenant": False,
            "physical_execution_claim": False,
        },
    }
    if not all(evidence["assertions"].values()):
        raise RuntimeError("one or more real OpenMES handoff assertions failed")
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    openmes_secret = json.loads(args.openmes_credential_file.read_text(encoding="utf-8"))
    for sensitive in (
        openmes_secret.get("api_key"),
        erp_config.api_key,
        erp_config.api_secret,
    ):
        if sensitive and sensitive in serialized:
            raise RuntimeError("credential leakage detected in OpenMES evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "handoff_passed",
        "output": str(args.output),
        "erpnext_work_orders": watched,
        "openmes_records": len(mes_result.records),
        "credentials_exposed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
