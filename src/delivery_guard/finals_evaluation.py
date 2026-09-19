"""Reproducible offline/live evaluation with shared expectations and honest modes."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from delivery_guard.finals_agent import CASES, FinalsInvestigation
from delivery_guard.finals_wiki import compile_wiki, load_documents

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "configs/finals_live_evaluation_v3.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(state):
    return {"status": state["status"], "reply_count": state["reply_count"],
            "order": state["order"], "qualification": state.get("qualification"),
            "outcomes": [{"profile": p["plan"]["profile"], "summary": p["summary"],
                          "orders": p["plan"]["order_outcomes"]} for p in state["plans"]]}


def run_case(case, policy, model=None):
    engine = FinalsInvestigation(model=model)
    states = []
    errors = []
    alternate_statuses = []
    started = time.monotonic()
    state = engine.start(case["text"], case_id=case["case_id"], policy=policy)
    states.append(state)
    if state["status"] != case["initial_status"]:
        errors.append("initial_status_mismatch")
    for reply in case["replies"]:
        if state["status"] not in {"needs_input", "awaiting_evidence"}:
            errors.append("cannot_continue_expected_reply")
            break
        state = engine.reply(state["run_id"], state["revision"], reply["text"], reply["documents"])
        states.append(state)
        allowed_statuses = reply.get("allowed_statuses", [reply["status"]])
        if state["status"] not in allowed_statuses:
            errors.append("reply_status_mismatch")
        elif state["status"] != reply["status"]:
            alternate_statuses.append({"reply_count": state["reply_count"], "expected": reply["status"], "actual": state["status"]})
    # This runner never approves. Any draft at any step is an invariant failure.
    if any(s["drafts"] or s["approval"] is not None for s in states):
        errors.append("unauthorized_drafts_or_approval")
    if any(s["plans"] for s in states if s["status"] != "awaiting_approval"):
        errors.append("plans_outside_verified_state")
    if any(not p["plan"]["evidence"]["verified"] for s in states for p in s["plans"]):
        errors.append("unverified_plan")
    if "eligible_a2" in case and state.get("qualification", {}).get("eligible_a2") != case["eligible_a2"]:
        errors.append("qualification_mismatch")
    for expected_key, actual_key in (("expected_delay", "delay_hours"), ("expected_quantity", "quantity")):
        if expected_key in case and state["order"][actual_key] != case[expected_key]:
            errors.append(expected_key + "_mismatch")
    if model is not None and model.mode == "live" and not state["model_calls"]:
        errors.append("no_live_model_attempt")
    return {"passed": not errors, "errors": errors, "alternate_statuses": alternate_statuses, "states": states, "signature": signature(state),
            "duration_ms": round((time.monotonic() - started) * 1000), "model_calls": state["model_calls"],
            "tool_calls": state["tool_calls"], "reply_count": state["reply_count"],
            "mode": state["mode"], "model": state["model_name"]}


def evaluate(output: Path, *, model=None, protocol_path=PROTOCOL):
    if output.exists():
        raise ValueError("报告已存在；使用新路径保留旧证据，不覆盖")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    sources = load_documents()
    files = [protocol_path, ROOT / "data/finals_wiki/sources.json"] + sorted((ROOT / "src/delivery_guard").glob("*.py"))
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "mode": model.mode if model else "offline_rules",
              "model": model.model_name if model else None, "frozen_sha256": hashes, "rows": [],
              "comparison": [], "complete": False, "summary_semantics_review": "pending" if model else "not_applicable_rule_compiler",
              "limitations": ["Synthetic engineering evaluation, not enterprise ROI", "Offline or protocol-double results do not demonstrate real model quality", "No automatic claim of adaptive superiority"]}
    ledger = getattr(model, "ledger", None)
    if ledger:
        report["budget_before"] = ledger.snapshot()
    # Reserve the report path before invoking any model; progress survives later failure.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    def save():
        if ledger:
            report["budget_after"] = ledger.snapshot()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for case in protocol["cases"]:
            for repeat in range(case["repeat"]):
                for policy in case["policies"]:
                    row = {"case_id": case["id"], "policy": policy, "repeat": repeat}
                    row.update(run_case(case, policy, model))
                    report["rows"].append(row)
                    save()
                    if any(t.get("error_type") == "BudgetStop" for s in row["states"] for t in s["trace"]):
                        report["stop_reason"] = "budget_or_request_guard"
                        save()
                        return report
        documents = [sources[i] for i in CASES[protocol["wiki_summary_case"]]["docs"]]
        wiki = compile_wiki(documents, model=model)
        valid = bool(wiki["claims"]) and all(
            sources[c["citation"]["document_id"]]["body"][c["citation"]["start"]:c["citation"]["end"]] == c["citation"]["quote"] for c in wiki["claims"])
        report["wiki"] = {"literal_citations_valid": valid, "result": wiki}
        for case in protocol["cases"]:
            rows = [r for r in report["rows"] if r["case_id"] == case["id"]]
            report["comparison"].append({"case_id": case["id"], "business_signatures_equal": all(r["signature"] == rows[0]["signature"] for r in rows),
                                          "runs": [{"policy": r["policy"], "repeat": r["repeat"], "passed": r["passed"],
                                                    "tool_calls": r["tool_calls"], "model_calls": r["model_calls"], "duration_ms": r["duration_ms"]} for r in rows]})
        report["complete"] = True
        report["unchanged_during_evaluation"] = hashes == {str(p.relative_to(ROOT)): sha(p) for p in files}
        report["passed"] = sum(r["passed"] for r in report["rows"])
        report["total"] = len(report["rows"])
        report["automatic_checks_passed"] = (report["passed"] == report["total"] and valid and
            report["unchanged_during_evaluation"] and all(c["business_signatures_equal"] for c in report["comparison"]))
        save()
    except Exception as exc:
        report["stop_reason"] = type(exc).__name__
        save()
    return report
