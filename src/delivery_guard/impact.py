"""Deterministic BOM explosion and incident impact analysis."""

from __future__ import annotations

from collections import defaultdict

from delivery_guard.models import (
    EvidencePath,
    ImpactReport,
    Incident,
    IncidentKind,
    Scenario,
)


def explode_bom(
    scenario: Scenario,
    product_id: str,
    quantity: int,
) -> tuple[dict[str, int], list[tuple[str, list[str]]]]:
    children: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for line in scenario.bom:
        children[line.parent_item_id].append((line.component_item_id, line.quantity))

    material_quantities: dict[str, int] = defaultdict(int)
    paths: list[tuple[str, list[str]]] = []

    def walk(item_id: str, required: int, path: list[str]) -> None:
        if not children[item_id]:
            material_quantities[item_id] += required
            paths.append((item_id, [*path, item_id]))
            return
        for component_id, component_quantity in children[item_id]:
            walk(
                component_id,
                required * component_quantity,
                [*path, item_id],
            )

    walk(product_id, quantity, [])
    return dict(material_quantities), paths


def analyze_impact(
    base: Scenario,
    adjusted: Scenario,
    incident: Incident,
    scenario_hash: str,
) -> ImpactReport:
    demand: dict[str, int] = defaultdict(int)
    all_paths: dict[str, list[tuple[str, list[str]]]] = {}
    for order in adjusted.orders:
        quantities, paths = explode_bom(adjusted, order.product_id, order.quantity)
        all_paths[order.order_id] = paths
        for material_id, quantity in quantities.items():
            demand[material_id] += quantity

    available: dict[str, int] = defaultdict(int)
    for entry in adjusted.inventory:
        available[entry.item_id] += entry.available

    horizon_supply: dict[str, int] = defaultdict(int)
    for source in adjusted.supplier_sources:
        if source.enabled and source.lead_time_hours <= adjusted.horizon_hours:
            horizon_supply[source.item_id] += source.max_quantity

    shortages = {
        material_id: max(0, required - available[material_id] - horizon_supply[material_id])
        for material_id, required in demand.items()
        if required > available[material_id] + horizon_supply[material_id]
    }

    target_materials: set[str] = set()
    affected_resources = [incident.target_id]
    if incident.kind in {IncidentKind.SUPPLIER_DELAY, IncidentKind.SUPPLIER_SHUTDOWN}:
        for source in base.supplier_sources:
            if source.source_id == incident.target_id or source.supplier_id == incident.target_id:
                target_materials.add(source.item_id)
    elif incident.kind == IncidentKind.INVENTORY_LOSS:
        target_materials.add(incident.target_id)

    affected_orders: list[str] = []
    evidence_paths: list[EvidencePath] = []
    for order in adjusted.orders:
        order_paths = all_paths[order.order_id]
        path_materials = {material_id for material_id, _ in order_paths}
        is_affected = bool(path_materials & target_materials)
        if incident.kind == IncidentKind.DEMAND_SURGE:
            is_affected = order.order_id == incident.target_id
        elif incident.kind == IncidentKind.LINE_OUTAGE:
            line = next(line for line in adjusted.production_lines if line.line_id == incident.target_id)
            operations = [
                operation
                for operation in adjusted.route_operations
                if operation.product_id == order.product_id
            ]
            is_affected = any(line.line_type in op.eligible_line_types for op in operations)
        if is_affected:
            affected_orders.append(order.order_id)
            for material_id, path in order_paths:
                if not target_materials or material_id in target_materials:
                    evidence_paths.append(
                        EvidencePath(
                            order_id=order.order_id,
                            material_id=material_id,
                            path=[incident.incident_id, incident.target_id, *path, order.order_id],
                        )
                    )

    notes = [
        "Incident free text was retained for audit but ignored by deterministic calculations.",
        f"Computed impact from {len(adjusted.orders)} orders and {len(adjusted.bom)} BOM lines.",
    ]
    if not affected_orders:
        notes.append("No direct order impact path was found; solver may still detect indirect constraints.")

    return ImpactReport(
        scenario_hash=scenario_hash,
        incident_id=incident.incident_id,
        affected_orders=sorted(affected_orders),
        affected_resources=affected_resources,
        material_demand=dict(sorted(demand.items())),
        projected_shortages=dict(sorted(shortages.items())),
        evidence_paths=evidence_paths,
        notes=notes,
    )
