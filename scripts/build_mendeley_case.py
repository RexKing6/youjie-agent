"""Rebuild the compact public-data case from the verified Mendeley workbook."""

from __future__ import annotations

import json
from pathlib import Path

from delivery_guard.mendeley import build_public_scenario


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb"
CASE = ROOT / "data/cases/mendeley_drill"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    scenario, lineage = build_public_scenario(RAW)
    write_json(CASE / "scenario.json", scenario.model_dump(mode="json"))
    write_json(CASE / "lineage.json", lineage)
    print(json.dumps({
        "scenario": str(CASE / "scenario.json"),
        "orders": len(scenario.orders),
        "units": sum(order.quantity for order in scenario.orders),
        "public_demand_rows": lineage["integrity"]["selected_demand_rows"],
        "sha256_verified": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
