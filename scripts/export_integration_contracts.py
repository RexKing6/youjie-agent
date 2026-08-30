"""Export project-owned JSON Schemas and stable ERP/MES contract examples."""

from __future__ import annotations

import json
from pathlib import Path

from delivery_guard.integration.contracts import (
    CallbackReceipt,
    CanonicalCommand,
    ExecutionCallback,
    TransportAck,
)


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    schemas = {
        "canonical_command.schema.json": CanonicalCommand.model_json_schema(),
        "transport_ack.schema.json": TransportAck.model_json_schema(),
        "execution_callback.schema.json": ExecutionCallback.model_json_schema(),
        "callback_receipt.schema.json": CallbackReceipt.model_json_schema(),
    }
    for name, schema in schemas.items():
        write_json(ROOT / "contracts/schemas" / name, schema)

    report = json.loads(
        (ROOT / "artifacts/integration_validation_report.json").read_text(encoding="utf-8")
    )
    for profile_name, profile in report["profiles"].items():
        run = profile["representative_run"]
        write_json(
            ROOT / "contracts/examples" / f"{profile_name}.example.json",
            {
                "profile": profile_name,
                "disclosure": run["disclosure"],
                "commands": run["commands"],
                "transport_acks": run["transport_acks"],
                "callbacks": run["callbacks"],
                "callback_receipts": run["callback_receipts"],
                "overall_business_status": run["overall_business_status"],
                "safety": run["safety"],
            },
        )
    print(f"exported {len(schemas)} schemas and {len(report['profiles'])} examples")


if __name__ == "__main__":
    main()
