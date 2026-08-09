from pathlib import Path

from delivery_guard.chaos_agent import ChaosDrillAgent
from delivery_guard.data import apply_incident, load_scenario
from delivery_guard.models import IncidentKind


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(ROOT / "data/cases/mendeley_drill/scenario.json")


def test_chaos_agent_is_seeded_bounded_and_covers_all_incident_families():
    agent = ChaosDrillAgent()
    first = agent.generate(SCENARIO, 20260810)
    second = agent.generate(SCENARIO, 20260810)
    assert first == second
    events = [agent.generate(SCENARIO, seed) for seed in range(5)]
    assert {event.incident.kind for event in events} == set(IncidentKind)
    for event in events:
        adjusted = apply_incident(SCENARIO, event.incident)
        assert adjusted.scenario_version == SCENARIO.scenario_version + 1
        assert event.incident.source_type == "synthetic_chaos_drill"
        assert "不能审批" in event.safety_boundary
