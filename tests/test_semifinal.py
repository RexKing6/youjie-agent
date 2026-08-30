from pathlib import Path

import pytest

from delivery_guard.data import load_scenario
from delivery_guard.evidence import load_evidence_bundle
from delivery_guard.semifinal import load_semifinal_cases, run_infeasible_case


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/cases/mendeley_drill"


def test_frozen_infeasible_case_stops_with_numeric_shortfall() -> None:
    cases = load_semifinal_cases(CASE / "semifinal_cases.json")
    result = run_infeasible_case(
        load_scenario(CASE / "scenario.json"),
        cases["infeasible_request"],
    )
    assert result["status"] == "infeasible"
    assert result["diagnostic"]["maximum_deliverable_by_due"] == 305
    assert result["diagnostic"]["maximum_deliverable_within_horizon"] == 305
    assert result["work_orders"] == []


def test_multiformat_evidence_detects_fresh_conflict() -> None:
    manifest = CASE / "evidence/manifest.json"
    if not manifest.exists():
        pytest.skip("binary evidence bundle is generated during semifinal build")
    result = load_evidence_bundle(manifest)
    assert all(item["hash_verified"] for item in result["records"])
    assert any(item["stale"] for item in result["records"])
    assert result["safe_to_solve"] is False
    assert result["conflicts"][0]["field_name"] == "delay_hours"
