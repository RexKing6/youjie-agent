"""Verified extraction of a small, traceable Mendeley automotive scenario."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pyxlsb import open_workbook

from delivery_guard.models import Scenario


DATASET_ID = "pr3sdy5vp3"
DATASET_VERSION = 1
DATASET_DOI = "10.17632/pr3sdy5vp3.1"
DATASET_URL = "https://data.mendeley.com/datasets/pr3sdy5vp3/1"
FILE_SHA256 = "1ea0bcdea3225d308be913c9ca0f377585e1863847c78d6e8eec10b6de82889e"
SOURCE_PERIOD = 61
TARGET_SIGNATURES = (
    ("DG8", "G0K", "Q2J"),
    ("DK8", "G0K", "Q2J"),
    ("D83", "G1Z", "BEV", "Q2J"),
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sheet(workbook: Any, name: str) -> list[dict[str, Any]]:
    with workbook.get_sheet(name) as sheet:
        rows = sheet.rows()
        header = [cell.v for cell in next(rows)]
        return [
            {**dict(zip(header, [cell.v for cell in row])), "_sheet_row": index}
            for index, row in enumerate(rows, start=2)
        ]


def _safe_id(value: str) -> str:
    return value.lower().replace("-", "_")


def build_public_scenario(raw_path: str | Path) -> tuple[Scenario, dict[str, Any]]:
    """Build a compact scenario while preserving every selected public row reference.

    Public facts and competition-only overlays are kept in separate lineage sections.
    """

    raw_path = Path(raw_path)
    actual_hash = file_sha256(raw_path)
    if actual_hash != FILE_SHA256:
        raise ValueError(f"Mendeley file hash mismatch: {actual_hash}")

    with open_workbook(str(raw_path)) as workbook:
        products = _read_sheet(workbook, "products")
        bom_rows = _read_sheet(workbook, "BOM")
        demand_rows = _read_sheet(workbook, "demands")
        inventory_rows = _read_sheet(workbook, "initial_inventories")
        arc_rows = _read_sheet(workbook, "arcs")
        capacity_rows = _read_sheet(workbook, "capacity_at_arc")

    product_group = {row["product_p"]: row["group_g"] for row in products}
    bom_by_parent: dict[str, list[str]] = defaultdict(list)
    bom_lineage: dict[tuple[str, str], int] = {}
    for row in bom_rows:
        if row["mother"] == row["child"]:
            continue
        bom_by_parent[row["mother"]].append(row["child"])
        bom_lineage[(row["mother"], row["child"])] = row["_sheet_row"]

    selected_demands: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in demand_rows:
        if int(row["period_t"]) != SOURCE_PERIOD:
            continue
        signature = tuple(bom_by_parent[row["product_p"]])
        if signature in TARGET_SIGNATURES:
            selected_demands[signature].append(row)
    counts = {signature: len(rows) for signature, rows in selected_demands.items()}
    if set(counts) != set(TARGET_SIGNATURES) or any(counts[item] == 0 for item in TARGET_SIGNATURES):
        raise ValueError(f"expected public signatures not found: {counts}")

    component_codes = sorted({code for signature in TARGET_SIGNATURES for code in signature})
    inventory_at_plant: dict[str, dict[str, Any]] = {}
    for row in inventory_rows:
        if row["node_n"] == "zp7" and row["product_p"] in component_codes:
            inventory_at_plant[row["product_p"]] = row

    lead_times = {
        row["group_g"]: int(row["process_lead_time_l_ij"] * 24)
        for row in arc_rows
        if row["ending_node_j"] == "zp7"
    }
    seat_capacity_row = next(
        row
        for row in capacity_rows
        if row["starting_node_i"] == "seat-supplier_inv"
        and row["ending_node_j"] == "zp7"
        and int(row["period_t"]) == SOURCE_PERIOD
    )
    car_capacity_row = next(
        row
        for row in capacity_rows
        if row["starting_node_i"] == "zp7"
        and row["ending_node_j"] == "zp8"
        and int(row["period_t"]) == SOURCE_PERIOD
    )
    if sum(counts.values()) > int(seat_capacity_row["capacity_c_ijt"]):
        raise ValueError("selected Q2J demand exceeds the public seat arc capacity")

    public_source = "data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb"
    product_ids = {signature: f"prd_cfg_{index + 1}" for index, signature in enumerate(TARGET_SIGNATURES)}
    component_ids = {code: f"mat_{_safe_id(code)}" for code in component_codes}
    priorities = ("critical", "high", "normal")
    customer_names = ("华东旗舰经销网络（模拟）", "区域车队客户（模拟）", "直营网点补货（模拟）")

    scenario_payload: dict[str, Any] = {
        "scenario_id": "scenario_mendeley_period61_drill",
        "scenario_version": 1,
        "horizon_hours": 96,
        "currency": "CNY",
        "provenance": {
            "as_of": "2026-08-09",
            "license": "Mixed: CC BY 4.0 public rows and Apache-2.0 synthetic overlay",
            "sources": [
                {
                    "source_id": "mendeley_pr3sdy5vp3_v1",
                    "source_type": "public_industry_grounded_randomized_dataset",
                    "source_ref": f"{DATASET_URL} (sha256:{FILE_SHA256})",
                    "license": "CC BY 4.0",
                    "derived_fields": [
                        "aggregate_product_ids",
                        "aggregate_order_quantities",
                        "period_to_hour_mapping",
                        "item_specific_seat_allocation_from_group_arc_capacity",
                        "discrete_line_calendar_from_daily_arc_capacity",
                    ],
                    "generated_rule": "Period 61 demand rows are grouped by identical BOM signature; source rows remain in lineage.json.",
                },
                {
                    "source_id": "competition_overlay_seed_20260809",
                    "source_type": "synthetic_competition_overlay",
                    "source_ref": "data/cases/mendeley_drill/lineage.json#synthetic_overlay",
                    "license": "Apache-2.0",
                    "derived_fields": [
                        "customer_names",
                        "priorities",
                        "unit_costs",
                        "emergency_supplier",
                        "recovery_budgets",
                        "incident_messages",
                        "route_duration",
                    ],
                    "generated_rule": "Deterministic seed 20260809; never represented as a Mendeley fact.",
                },
            ],
            "derived_fields": [
                "aggregated_customer_orders",
                "planning_hours",
                "competition_policy_and_cost_fields",
            ],
            "seed": 20260809,
        },
        "items": [
            {
                "item_id": product_ids[signature],
                "item_type": "finished_good",
                "name": "公开车辆配置 " + "+".join(signature),
                "unit": "vehicle",
                "safety_stock": 0,
            }
            for signature in TARGET_SIGNATURES
        ] + [
            {
                "item_id": component_ids[code],
                "item_type": "raw_material",
                "name": f"Mendeley {product_group[code]} {code}",
                "unit": "unit",
                "safety_stock": 0,
            }
            for code in component_codes
        ],
        "bom": [
            {
                "parent_item_id": product_ids[signature],
                "component_item_id": component_ids[code],
                "quantity": 1,
            }
            for signature in TARGET_SIGNATURES
            for code in signature
        ],
        "inventory": [
            {
                "item_id": component_ids[code],
                "location_id": "loc_zp7",
                "on_hand": int(inventory_at_plant.get(code, {}).get("initial_inventory_I_np0", 0)),
                "reserved": 0,
                "quality_hold": 0,
            }
            for code in component_codes
        ],
        "suppliers": [
            {"supplier_id": "sup_seat_public", "name": "Mendeley seat supplier", "risk_score": 35},
            {"supplier_id": "sup_seat_emergency_sim", "name": "应急座椅供应商（模拟）", "risk_score": 55},
        ],
        "supplier_sources": [
            {
                "source_id": "src_public_seat_q2j",
                "supplier_id": "sup_seat_public",
                "item_id": component_ids["Q2J"],
                "lead_time_hours": lead_times["seat"],
                "max_quantity": sum(counts.values()),
                "unit_cost": 0,
                "incremental_unit_cost": 0,
                "committed_quantity": sum(counts.values()),
                "enabled": True,
            },
            {
                "source_id": "src_sim_emergency_q2j",
                "supplier_id": "sup_seat_emergency_sim",
                "item_id": component_ids["Q2J"],
                "lead_time_hours": 12,
                "max_quantity": 100,
                "unit_cost": 8,
                "incremental_unit_cost": 8,
                "committed_quantity": 0,
                "enabled": True,
            },
        ],
        "production_lines": [
            {
                "line_id": "line_zp7_public",
                "line_type": "vehicle_assembly",
                "unavailable_windows": [],
                "available_windows": [
                    {"start_hour": day * 24, "end_hour": day * 24 + 20}
                    for day in range(4)
                ],
                "incremental_cost_per_batch": 0,
                "overtime": False,
            }
        ],
        "route_operations": [
            {
                "operation_id": f"op_assemble_cfg_{index + 1}",
                "product_id": product_ids[signature],
                "sequence": 1,
                "eligible_line_types": ["vehicle_assembly"],
                "batch_size": int(car_capacity_row["capacity_c_ijt"] // 5),
                "duration_per_batch_hours": 4,
            }
            for index, signature in enumerate(TARGET_SIGNATURES)
        ],
        "orders": [
            {
                "order_id": f"ord_public_cfg_{index + 1}",
                "product_id": product_ids[signature],
                "quantity": counts[signature],
                "release_hour": 0,
                "due_hour": 24,
                "priority": priorities[index],
                "frozen": index == 0,
                "customer_name": customer_names[index],
                "order_group_id": f"public_period61_cfg_{index + 1}",
                "split_allowed": False,
                "must_ship_complete": True,
                "late_penalty_per_unit_hour": (50, 30, 10)[index],
            }
            for index, signature in enumerate(TARGET_SIGNATURES)
        ],
        "profile_recovery_budgets": {
            "service_first": 800,
            "balanced": 400,
            "stability_first": 0,
        },
    }

    lineage = {
        "dataset": {
            "id": DATASET_ID,
            "version": DATASET_VERSION,
            "doi": DATASET_DOI,
            "url": DATASET_URL,
            "license": "CC BY 4.0",
            "file": public_source,
            "sha256": actual_hash,
            "source_period": SOURCE_PERIOD,
        },
        "public_rows": {
            "demands": {
                product_ids[signature]: [
                    {
                        "sheet": "demands",
                        "row": row["_sheet_row"],
                        "product_p": row["product_p"],
                        "demand": int(row["demand_d_npt"]),
                        "period": int(row["period_t"]),
                    }
                    for row in selected_demands[signature]
                ]
                for signature in TARGET_SIGNATURES
            },
            "bom": [
                {
                    "sheet": "BOM",
                    "row": bom_lineage[(selected_demands[signature][0]["product_p"], code)],
                    "source_vehicle": selected_demands[signature][0]["product_p"],
                    "component": code,
                    "quantity": 1,
                }
                for signature in TARGET_SIGNATURES
                for code in signature
            ],
            "inventory": [
                {
                    "sheet": "initial_inventories",
                    "row": row["_sheet_row"],
                    "node": row["node_n"],
                    "product": row["product_p"],
                    "initial_inventory": int(row["initial_inventory_I_np0"]),
                }
                for row in inventory_at_plant.values()
            ],
            "seat_capacity": {
                "sheet": "capacity_at_arc",
                "row": seat_capacity_row["_sheet_row"],
                "capacity": int(seat_capacity_row["capacity_c_ijt"]),
            },
            "vehicle_capacity": {
                "sheet": "capacity_at_arc",
                "row": car_capacity_row["_sheet_row"],
                "capacity": int(car_capacity_row["capacity_c_ijt"]),
            },
        },
        "derived_aggregates": {
            product_ids[signature]: {
                "bom_signature": list(signature),
                "quantity": counts[signature],
                "source_row_count": len(selected_demands[signature]),
                "sum_of_source_demand": int(sum(row["demand_d_npt"] for row in selected_demands[signature])),
            }
            for signature in TARGET_SIGNATURES
        },
        "synthetic_overlay": {
            "seed": 20260809,
            "fields": scenario_payload["provenance"]["sources"][1]["derived_fields"],
            "reason": "The public workbook has no customer SLA, commercial priority, emergency premium, incident message, or human approval records.",
        },
        "integrity": {
            "selected_demand_rows": sum(len(rows) for rows in selected_demands.values()),
            "selected_demand_sum": int(sum(sum(row["demand_d_npt"] for row in rows) for rows in selected_demands.values())),
            "aggregate_order_sum": sum(counts.values()),
            "signature_counts": Counter({"+".join(key): value for key, value in counts.items()}),
        },
    }
    return Scenario.model_validate(scenario_payload), lineage
