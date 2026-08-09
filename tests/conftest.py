from __future__ import annotations

import copy
from pathlib import Path

import pytest

from delivery_guard.data import load_incident, load_scenario
from delivery_guard.workflow import RecoveryWorkflow


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def scenario():
    return load_scenario(ROOT / "data/demo_factory.json")


@pytest.fixture(scope="session")
def supplier_delay():
    return load_incident(ROOT / "data/incidents/supplier_delay.json")


@pytest.fixture(scope="session")
def solved_workflow_template(scenario, supplier_delay):
    workflow = RecoveryWorkflow(scenario, supplier_delay)
    workflow.analyze()
    workflow.solve()
    return workflow


@pytest.fixture()
def solved_workflow(solved_workflow_template):
    return copy.deepcopy(solved_workflow_template)
