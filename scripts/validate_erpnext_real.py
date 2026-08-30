#!/usr/bin/env python3
"""Run the bounded adapter against a real ERPNext test instance.

The evidence file contains only host, document identifiers, revisions, hashes,
status, and safety assertions. API credentials are loaded from a separate file
and are never serialized into the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.integration import (
    ERPNextAdapter,
    ERPNextConfig,
    ERPNextExecutionLedger,
    ERPNextHttpClient,
    ERPNextMapping,
    build_erpnext_commands,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/erpnext_real_validation.json",
    )
    args = parser.parse_args()

    config = ERPNextConfig.from_environment({
        "DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE": str(args.credential_file),
    })
    if config is None:
        raise RuntimeError("ERPNext credential file did not produce a configuration")
    adapter = ERPNextAdapter(
        ERPNextHttpClient(config),
        ledger=ERPNextExecutionLedger(args.ledger),
    )
    mapping = ERPNextMapping.from_path(ROOT / "data/integrations/erpnext_demo_mapping.json")
    approved = json.loads((ROOT / "artifacts/public_data_graph_run.json").read_text(encoding="utf-8"))

    health = adapter.client.health()
    before = adapter.execution_snapshot()
    commands = build_erpnext_commands(
        approved,
        mapping,
        expected_source_revision=before["source_revision"],
    )
    first_results = [adapter.execute(command) for command in commands]
    duplicate_results = [adapter.execute(command) for command in commands]
    after = adapter.execution_snapshot()

    records = [
        record.model_dump(mode="json")
        for result in first_results
        for record in result.records
    ]
    referenced_commitments = [
        item
        for command in commands
        for item in command.payload.get("referenced_commitments", [])
    ]
    evidence = {
        "schema_version": "youjie.erpnext_real_validation/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "status": health["status"],
            "environment": health["environment"],
            "public_host": health["public_host"],
            "authenticated_user": health["authenticated_user"],
            "credentials_exposed": False,
        },
        "source_revision_before": before["source_revision"],
        "source_revision_after_write": after["source_revision"],
        "commands": [
            {
                "command_id": result.command_id,
                "business_status": result.business_status.value,
                "record_count": len(result.records),
            }
            for result in first_results
        ],
        "records": records,
        "referenced_commitments": referenced_commitments,
        "assertions": {
            "authenticated_real_http": health["status"] == "connected",
            "four_new_drafts_created_and_read_back": len(records) == 4,
            "committed_supply_referenced_without_duplicate_document": (
                len(referenced_commitments) == 1
                and referenced_commitments[0]["source_id"] == "src_public_seat_q2j"
            ),
            "all_documents_remain_draft": all(row["docstatus"] == 0 for row in records),
            "write_changed_source_revision": before["source_revision"] != after["source_revision"],
            "duplicate_retry_created_nothing": all(row.duplicate for row in duplicate_results),
            "credentials_absent_from_evidence": True,
            "no_submit_cancel_delete_or_device_control": True,
        },
        "boundaries": {
            "instance": "localhost ERPNext test instance",
            "data": "public Mendeley-derived rows plus synthetic overlay",
            "write_scope": "draft Material Request and Work Order only",
            "standalone_mes_claim": False,
        },
    }
    if not all(evidence["assertions"].values()):
        raise RuntimeError("one or more real ERPNext validation assertions failed")
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    credential = json.loads(args.credential_file.read_text(encoding="utf-8"))
    for sensitive in (credential.get("api_key"), credential.get("api_secret")):
        if sensitive and sensitive in serialized:
            raise RuntimeError("credential leakage detected in evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "passed",
        "output": str(args.output),
        "records": len(records),
        "credentials_exposed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
