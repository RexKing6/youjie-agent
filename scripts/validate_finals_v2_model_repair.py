"""Real-model development regression, preserving first failures and source hashes."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from delivery_guard.finals_agent import CASES, FinalsInvestigation
from delivery_guard.finals_live import FinalsLiveModel
from delivery_guard.finals_wiki import compile_wiki, load_documents

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve prior reports; select a new output")
    protocol_path = ROOT / "configs/finals_v2_model_repair_dev.json"
    protocol = json.loads(protocol_path.read_text())
    paths = [protocol_path, Path(__file__), *sorted((ROOT / "src/delivery_guard").glob("finals_*.py")), ROOT / "data/finals_wiki/sources.json"]
    def hashes():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    model = FinalsLiveModel(operator_token_plan=True)
    report = {"split": protocol["split"], "mode": "live", "complete": False, "hashes": hashes(),
              "rows": [], "usage_before": model.ledger.snapshot()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def failure(exc):
        return {"pass": False, "error_type": type(exc).__name__, "error_code": getattr(exc, "code", "MODEL_OR_TRANSPORT_ERROR"),
                "document_id": getattr(exc, "document_id", "")}
    save()
    registry = load_documents()
    for variant in protocol["variants"]:
        docs = [deepcopy(registry[i]) for i in CASES[protocol["case"]]["docs"]]
        for d in docs:
            for old, new in variant["replacements"].items():
                d["body"] = d["body"].replace(old, new)
        for repeat in range(protocol["repeats"]):
            row = {"kind": "wiki", "variant": variant["id"], "repeat": repeat}
            started = time.monotonic()
            try:
                wiki = compile_wiki(docs, model)
                row.update({"pass": len(wiki["claims"]) == len(docs), "wiki": wiki,
                            "semantic_review": "pending_manual_review"})
            except Exception as exc:
                row.update(failure(exc))
            row["seconds"] = round(time.monotonic()-started, 3)
            report["rows"].append(row)
            save()
            print(row["kind"], variant["id"], repeat, row["pass"], flush=True)
    for text in protocol["followup_inputs"]:
        engine = FinalsInvestigation(model=model)
        row = {"kind": "followup", "input": text}
        try:
            state = engine.start("A1延期24小时，请检查O-208当前替代料依据。")
            state = engine.reply(state["run_id"], state["revision"], text, [])
            followups = [t for t in state["trace"] if t["node"] == "targeted_followup"]
            row.update({"pass": state["status"] == "awaiting_evidence" and len(followups) == 1
                        and not followups[0].get("candidate_rejected", True), "state": state})
        except Exception as exc:
            row.update(failure(exc))
        report["rows"].append(row)
        save()
        print("followup", row["pass"], flush=True)
    report.update(complete=True, unchanged=report["hashes"] == hashes(), usage_after=model.ledger.snapshot())
    report["automatic_pass"] = report["unchanged"] and all(r["pass"] for r in report["rows"])
    save()
    raise SystemExit(0 if report["automatic_pass"] else 1)


if __name__ == "__main__":
    main()
