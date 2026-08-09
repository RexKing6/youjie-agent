"""Scenario loading and deterministic incident application."""

from __future__ import annotations

import json
from pathlib import Path

from delivery_guard.hashing import stable_hash
from delivery_guard.models import (
    CustomerOrder,
    Incident,
    IncidentKind,
    Scenario,
    TimeWindow,
)


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def load_incident(path: str | Path) -> Incident:
    return Incident.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def scenario_incident_hash(scenario: Scenario, incident: Incident) -> str:
    return stable_hash({"scenario": scenario, "incident": incident})


def apply_incident(scenario: Scenario, incident: Incident) -> Scenario:
    """Return a new validated scenario; incident description is never executed."""

    payload = scenario.model_dump(mode="json")
    payload["scenario_version"] += 1

    if incident.kind == IncidentKind.SUPPLIER_DELAY:
        matches = 0
        for source in payload["supplier_sources"]:
            if source["source_id"] == incident.target_id or source["supplier_id"] == incident.target_id:
                source["lead_time_hours"] += incident.delay_hours
                matches += 1
        if not matches:
            raise ValueError(f"supplier delay target not found: {incident.target_id}")

    elif incident.kind == IncidentKind.SUPPLIER_SHUTDOWN:
        matches = 0
        for source in payload["supplier_sources"]:
            if source["source_id"] == incident.target_id or source["supplier_id"] == incident.target_id:
                source["enabled"] = False
                matches += 1
        if not matches:
            raise ValueError(f"supplier shutdown target not found: {incident.target_id}")

    elif incident.kind == IncidentKind.INVENTORY_LOSS:
        matches = 0
        for entry in payload["inventory"]:
            if entry["item_id"] == incident.target_id:
                entry["on_hand"] -= incident.loss_quantity
                if entry["on_hand"] < 0:
                    raise ValueError(
                        f"inventory loss would make {incident.target_id} negative: "
                        f"loss={incident.loss_quantity}"
                    )
                if entry["reserved"] + entry["quality_hold"] > entry["on_hand"]:
                    raise ValueError(
                        f"inventory loss violates reservations/quality hold for {incident.target_id}"
                    )
                matches += 1
        if not matches:
            raise ValueError(f"inventory target not found: {incident.target_id}")

    elif incident.kind == IncidentKind.LINE_OUTAGE:
        matches = 0
        for line in payload["production_lines"]:
            if line["line_id"] == incident.target_id:
                line["unavailable_windows"].append(
                    TimeWindow(
                        start_hour=incident.start_hour,
                        end_hour=incident.end_hour,
                    ).model_dump(mode="json")
                )
                matches += 1
        if not matches:
            raise ValueError(f"line outage target not found: {incident.target_id}")

    elif incident.kind == IncidentKind.DEMAND_SURGE:
        matches = 0
        for order in payload["orders"]:
            if order["order_id"] == incident.target_id:
                updated = CustomerOrder.model_validate(
                    {**order, "quantity": order["quantity"] + incident.quantity_delta}
                )
                order.update(updated.model_dump(mode="json"))
                matches += 1
        if not matches:
            raise ValueError(f"demand surge target not found: {incident.target_id}")

    return Scenario.model_validate(payload)
