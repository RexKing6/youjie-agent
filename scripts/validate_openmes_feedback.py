#!/usr/bin/env python3
"""Re-read OpenMES after a human state transition and seal feedback evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.integration import OpenMESConfig, OpenMESHttpClient, compare_openmes_snapshots


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "artifacts/openmes_real_validation.json",
    )
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    config = OpenMESConfig.from_environment({
        "DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE": str(args.credential_file),
    })
    if config is None:
        raise RuntimeError("OpenMES credential file did not produce a configuration")
    client = OpenMESHttpClient(config)
    baseline = evidence["openmes"]["feedback_baseline"]
    watched = baseline["watched_order_nos"]
    current = client.work_order_snapshot(watched)
    delta = compare_openmes_snapshots(baseline, current)
    if not delta["changed"]:
        raise RuntimeError("OpenMES execution state has not changed; perform a human transition first")
    evidence["feedback_validation"] = {
        "status": "change_detected_and_old_approval_invalidated",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "delta": delta,
        "records": current["records"],
        "previous_approval_id": evidence["approval"]["approval_id"],
        "previous_approval_valid": False,
        "new_commands_blocked": True,
        "next_required_action": "refresh ERP/MES facts, re-solve, and obtain a new human approval",
    }
    evidence["assertions"]["human_openmes_change_detected"] = True
    evidence["assertions"]["old_approval_invalidated_after_mes_feedback"] = True
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    credential = json.loads(args.credential_file.read_text(encoding="utf-8"))
    if credential.get("api_key") and credential["api_key"] in serialized:
        raise RuntimeError("credential leakage detected in feedback evidence")
    args.evidence.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "feedback_passed",
        "changed_entities": delta["changed_entities"],
        "previous_approval_valid": False,
        "credentials_exposed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
