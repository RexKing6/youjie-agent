"""Frozen concurrent synthetic task evaluation; no approval or external writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import time

from delivery_guard.finals_evaluation import run_case
from delivery_guard.finals_live import FinalsLiveModel

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--workers",type=int,default=3,choices=[1,2,3])
    parser.add_argument("--protocol",type=Path,default=ROOT/"configs/finals_v2_tasks_v1.json")
    args=parser.parse_args()
    if args.output.exists(): parser.error("Existing evidence must be preserved")
    protocol_path=args.protocol.resolve()
    protocol=json.loads(protocol_path.read_text())
    inherited=[]
    if "base_protocol" in protocol:
        base_path=ROOT/protocol["base_protocol"]
        base=json.loads(base_path.read_text())
        lookup={c["id"]:c for c in base["cases"]}
        protocol["cases"]=[{**lookup[i],"split":"development"} for i in protocol["development_ids"]]+protocol["cases"]
        inherited=[base_path]
    paths=[protocol_path,*inherited,Path(__file__),ROOT/"data/finals_wiki/sources.json",*sorted((ROOT/"src/delivery_guard").rglob("*.py"))]
    def hashes(): return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=hashes()
    report={"mode":"live" if args.live else "offline_rules","frozen_sha256":before,"complete":False,"rows":[],
            "limitations":protocol["scope"],"no_external_writes":True,"automatic_retry":False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save(): args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    save()
    def run(case,policy,repeat):
        model=FinalsLiveModel(operator_token_plan=True) if args.live else None
        row={"case_id":case["id"],"split":case["split"],"policy":policy,"repeat":repeat}
        started=time.monotonic()
        try:
            row.update(run_case(case,policy,model))
            trace=row["states"][-1]["trace"]
            followups=[t for t in trace if t["node"]=="targeted_followup"]
            row["model_rejections"]=[t for t in trace if t.get("candidate_rejected") or t.get("error_type")]
            row["followup_count"]=len(followups)
            row["followup_rejected_count"]=sum(bool(t.get("candidate_rejected")) for t in followups)
        except Exception as exc:
            row.update(passed=False,errors=[type(exc).__name__],states=[],model_rejections=[],followup_count=0,followup_rejected_count=0)
        row["elapsed_seconds"]=round(time.monotonic()-started,3)
        return row
    jobs=[(case,policy,repeat) for case in protocol["cases"] for repeat in range(case["repeat"]) for policy in case["policies"]]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run,*job) for job in jobs]
        for future in as_completed(futures):
            row=future.result()
            report["rows"].append(row)
            save()
            print(len(report["rows"]),len(jobs),row["case_id"],row["policy"],row["repeat"],row["passed"],flush=True)
    report["unchanged"]=before==hashes()
    report["complete"]=len(report["rows"])==len(jobs)
    report["groups"]={}
    for split in ("development","heldout_expression"):
        for policy in ("fixed","adaptive"):
            rows=[r for r in report["rows"] if r["split"]==split and r["policy"]==policy]
            if not rows:
                continue  # A development-only regression has no heldout group.
            times=sorted(r["elapsed_seconds"] for r in rows)
            report["groups"][split+"/"+policy]={"tasks":len(rows),"passed":sum(r["passed"] for r in rows),
                "model_rejections":sum(len(r["model_rejections"]) for r in rows),
                "followup_count":sum(r["followup_count"] for r in rows),"followup_rejections":sum(r["followup_rejected_count"] for r in rows),
                "p50_seconds":statistics.median(times),"p95_seconds":times[min(len(times)-1,int(len(times)*.95))]}
    report["automatic_checks_passed"]=report["unchanged"] and report["complete"] and all(r["passed"] for r in report["rows"])
    save()
    print(json.dumps(report["groups"],ensure_ascii=False),flush=True)
    raise SystemExit(0 if report["automatic_checks_passed"] else 1)


if __name__=="__main__": main()
