"""Frozen-protocol local challenge checks; synthetic, offline, not LLM accuracy."""
from __future__ import annotations

import argparse
import json
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.finals_api import FinalsApplication
from delivery_guard.finals_wiki import compile_wiki, load_documents, qualify
from delivery_guard.hashing import stable_hash

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = ROOT / args.output
    if path.exists():
        raise SystemExit("Choose a new report path; previous evidence is preserved")
    protocol = json.loads((ROOT / "configs/finals_validation_v1.json").read_text())
    rng = random.Random(protocol["seed"])
    rows = []

    def record(name, family, check):
        try:
            evidence = check()
            rows.append({"name": name, "family": family, "pass": True, "evidence": evidence})
        except Exception as exc:
            rows.append({"name": name, "family": family, "pass": False, "error_type": type(exc).__name__})

    def terminal(text, case="ready", expected="awaiting_approval", qty=600):
        s = FinalsInvestigation().start(text, case_id=case)
        assert s["status"] == expected
        assert not s["drafts"] and s["approval"] is None
        if expected == "awaiting_approval":
            assert s["order"]["quantity"] == qty
            assert all(p["plan"]["evidence"]["verified"] for p in s["plans"])
        else:
            assert not s["plans"]
        return {k: s[k] for k in ("status", "tool_calls", "model_calls", "reply_count", "duration_ms")}

    for i, text in enumerate(("Ａ１延期１２小时", "a1延期 36 小时", "O208 A1需求750件，延期48小时", "  A1延迟0小时  ")):
        record(f"normalized_{i}", "unicode_spacing_and_case", lambda t=text: terminal(t, expected="no_disruption" if "0小时" in t else "awaiting_approval", qty=750 if "750" in t else 600))
    for i in range(8):
        qty = rng.randint(201, 1200)
        text = f"客户丙O-909的A1需要{qty}件，延期12小时"
        record(f"scope_quantity_{i}", "simultaneous_scope_and_quantity_changes", lambda t=text: terminal(t, expected="needs_input"))

    source = load_documents()
    order = {"order_id": "O-208", "customer": "客户乙", "revision": "B", "quantity": 600, "a1_available": 200}
    stock = {"batch": "B17", "on_hand": 500, "hold": 100, "reserved": 0, "revision": 1}
    for i in range(8):
        ids = ["AP-CURRENT", "QC-PASS", "AP-OTHER", "HISTORY-01", "CHAT-01"]
        rng.shuffle(ids)
        def permutation(ids=ids):
            docs = [source[k] for k in ids]
            q = qualify(order, docs, stock)
            assert q["eligible_a2"] == 400 and not q["gaps"]
            wiki = compile_wiki(docs)
            for claim in wiki["claims"]:
                c = claim["citation"]
                d = source[c["document_id"]]
                assert d["body"][c["start"]:c["end"]] == c["quote"]
                assert c["source_hash"] == stable_hash(d["body"])
            return {"eligible_a2": q["eligible_a2"], "literal_citations": len(wiki["claims"])}
        record(f"source_permutation_{i}", "irrelevant_document_permutation", permutation)

    def contradiction():
        q = qualify(order, [source[k] for k in ("AP-CURRENT", "AP-DENY")], stock)
        assert set(q["gaps"]) >= {"approval_conflict", "quality_missing"}
        assert q["eligible_a2"] == 0
        return q
    record("conflict_and_absent_quality", "contradiction_with_missing_quality", contradiction)

    def stale():
        e = FinalsInvestigation()
        s = e.start("A1延期36小时", case_id="partial")
        old = deepcopy(s)
        s = e.feedback(s["run_id"], s["revision"], 350)
        assert s["qualification"]["eligible_a2"] == 150
        try:
            e.approve(old["run_id"], old["revision"], old["plans"][0]["plan"]["plan_id"], "tester")
        except ValueError:
            pass
        else:
            raise AssertionError("stale approval accepted")
        assert not e.runs[s["run_id"]]["drafts"]
        return {"old_revision": old["revision"], "current_revision": s["revision"], "old_approval_rejected": True}
    record("stale_after_feedback", "stale_reply_after_feedback", stale)

    def isolation():
        e = FinalsInvestigation()
        a, b = e.start("A1延期12小时"), e.start("A1延期48小时")
        a = e.reply(a["run_id"], a["revision"], "当前订单批准", ["AP-CURRENT"])
        assert a["status"] == "awaiting_approval"
        assert e.runs[b["run_id"]]["status"] == "awaiting_evidence"
        assert not e.runs[b["run_id"]]["plans"]
        return {"isolated": True}
    record("run_state_isolation", "cross_run_replay", isolation)

    comparison = FinalsApplication().post("/compare", {"text": "A1延期24小时"})
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": stable_hash(protocol), "source_sha256": stable_hash(source),
        "mode": "offline_rules", "model_requests": 0, "actual_external_business_writes": 0,
        "split": "engineering-authored challenge families; after first run these are development regression, not untouched holdout",
        "rows": rows, "passed": sum(r["pass"] for r in rows), "total": len(rows),
        "comparison": comparison,
        "limits": ["Not a real-model evaluation", "Not an industrial ROI measurement", "Code fixes consume these cases as development", "No production identity verification or live ERP/MES integration in this new case"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} offline challenge checks; report={path}")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
