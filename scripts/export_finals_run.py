"""Export one explicitly selected local synthetic run, never credentials."""
import argparse
import json
from pathlib import Path
from delivery_guard.finals_provenance import export_evidence, runtime_provenance
from delivery_guard.finals_wiki import load_documents
from delivery_guard.integration.finals_state import FinalsStateStore

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--confirm-synthetic-data",action="store_true")
    args=parser.parse_args()
    if not args.confirm_synthetic_data: parser.error("Confirm that the selected run contains only synthetic project data")
    if args.output.exists(): parser.error("Preserve existing evidence")
    store=FinalsStateStore(ROOT/".tmp/finals_v2/runs")
    state=store.load(args.run_id)
    report=export_evidence(state,runtime_provenance(load_documents(),state.get("model_name","")),
                           store.journal_evidence(args.run_id))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"run_id":state["run_id"],"status":state["status"],"state_sha256":report["state_sha256"]}))


if __name__=="__main__": main()
