from __future__ import annotations

from pydantic import ValidationError
import pytest

from delivery_guard.hashing import stable_hash
from delivery_guard.models import Scenario


def test_demo_scenario_is_valid(scenario):
    assert scenario.scenario_id == "goai_demo_factory"
    assert len(scenario.orders) == 8
    assert stable_hash(scenario) == stable_hash(scenario.model_copy(deep=True))


def test_duplicate_order_is_rejected(scenario):
    raw = scenario.model_dump(mode="json")
    raw["orders"].append(raw["orders"][0])
    with pytest.raises(ValidationError, match="duplicate order_id"):
        Scenario.model_validate(raw)


def test_bom_cycle_is_rejected(scenario):
    raw = scenario.model_dump(mode="json")
    raw["bom"].extend(
        [
            {"parent_item_id": "prd_sensor_hub", "component_item_id": "prd_gateway", "quantity": 1},
            {"parent_item_id": "prd_gateway", "component_item_id": "prd_sensor_hub", "quantity": 1},
        ]
    )
    with pytest.raises(ValidationError, match="cyclic BOM"):
        Scenario.model_validate(raw)


def test_negative_inventory_is_rejected(scenario):
    raw = scenario.model_dump(mode="json")
    raw["inventory"][0]["on_hand"] = -1
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


def test_dangling_reference_is_rejected(scenario):
    raw = scenario.model_dump(mode="json")
    raw["supplier_sources"][0]["item_id"] = "mat_missing"
    with pytest.raises(ValidationError, match="unknown item"):
        Scenario.model_validate(raw)
