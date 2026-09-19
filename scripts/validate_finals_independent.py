"""Freeze before execution; mathematical cross-check outside the production solver."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.finals_agent import FinalsInvestigation

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(config, scenario, policy):
    qty, delay, doc, hold = scenario
    e = FinalsInvestigation()
    s = e.start(f"订单O-208的A1需要{qty}件，延期{delay}小时，请调查替代依据", policy=policy)
    assert s["status"] == "awaiting_evidence" and not s["plans"]
    s = e.reply(s["run_id"], s["revision"], "技术同事说A2以前用过，请核对", [])
    assert s["status"] == "awaiting_evidence" and not s["plans"]
    assert s["reply_count"] == 1
    s = e.reply(s["run_id"], s["revision"], "附上当前订单客户批准，核对范围后计算", [doc])
    assert s["reply_count"] == 2 and s["status"] == "awaiting_approval"
    assert not s["drafts"] and s["approval"] is None
    cap = 400 if doc == "AP-CURRENT" else 300
    signatures = []

    def verify(current, frozen):
        eligible = min(cap, 500 - frozen, qty - 200)
        shortage = max(0, qty - 200 - eligible)
        duration = math.ceil(qty / 600) * config["production_hours_per_600"]
        service = next(p for p in current["plans"] if p["plan"]["profile"] == "service_first")
        # All approved shortage fits the 9600-yuan service budget in this scope.
        completion = duration + (config["normal_arrival_hour"] if shortage else 0)
        assert current["qualification"]["eligible_a2"] == eligible
        assert service["summary"]["recovery_cost"] == shortage * 8
        assert service["plan"]["order_outcomes"][0]["completion_hour"] == completion
        assert all(p["plan"]["evidence"]["verified"] for p in current["plans"])
        assert current["model_calls"] == 0
        return {"eligible_a2": eligible, "shortage": shortage, "service_cost": shortage * 8, "service_completion": completion}

    signatures.append(verify(s, 100))
    s = e.approve(s["run_id"], s["revision"], s["plans"][0]["plan"]["plan_id"], "independent-local-test")
    assert s["drafts"]
    old_revision, old_plan = s["revision"], s["plans"][0]["plan"]["plan_id"]
    s = e.feedback(s["run_id"], s["revision"], hold)
    assert s["status"] == "awaiting_approval" and not s["drafts"] and s["approval"] is None
    assert not s["history"][-1]["approval"]["valid"]
    signatures.append(verify(s, hold))
    try:
        e.approve(s["run_id"], old_revision, old_plan, "stale-replay")
    except ValueError:
        pass
    else:
        raise AssertionError("stale approval accepted")
    return {"signature": signatures, "status": s["status"], "tool_calls": s["tool_calls"], "model_calls": s["model_calls"], "reply_count": s["reply_count"], "duration_ms": s["duration_ms"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise SystemExit("Report exists; refusing overwrite")
    protocol = ROOT / "configs/finals_independent_v2.json"
    config = json.loads(protocol.read_text())
    population = list(itertools.product(config["quantities"], config["delay_hours"], config["approval_documents"], config["post_approval_holds"]))
    cases = random.Random(config["seed"]).sample(population, config["sample_count"])
    files = [protocol, Path(__file__), ROOT / "data/finals_wiki/sources.json"]
    files += [ROOT / "src/delivery_guard" / name for name in ("finals_agent.py", "finals_wiki.py", "solver.py", "workflow.py", "models.py")]
    frozen = {str(p.relative_to(ROOT)): digest(p) for p in files}
    report = {"date_utc": datetime.now(timezone.utc).isoformat(), "scope": config["scope"], "frozen_sha256": frozen,
              "samples_frozen_before_execution": cases, "rows": []}
    for index, scenario in enumerate(cases):
        reference = None
        for policy in config["policies"]:
            for repeat in range(config["repeats"]):
                row = {"case": index, "policy": policy, "repeat": repeat}
                try:
                    result = evaluate(config, scenario, policy)
                    if reference is None:
                        reference = result["signature"]
                    assert result["signature"] == reference
                    row.update(result, passed=True)
                except Exception as exc:
                    row.update(passed=False, error_type=type(exc).__name__)
                report["rows"].append(row)
    report["unchanged_during_evaluation"] = frozen == {str(p.relative_to(ROOT)): digest(p) for p in files}
    report["passed"] = sum(r["passed"] for r in report["rows"])
    report["total"] = len(report["rows"])
    report["live_model_requests"] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} independent synthetic runs; source unchanged={report['unchanged_during_evaluation']}")
    raise SystemExit(0 if report["passed"] == report["total"] and report["unchanged_during_evaluation"] else 1)


if __name__ == "__main__":
    main()
