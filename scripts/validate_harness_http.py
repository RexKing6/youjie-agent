"""User-authorized synthetic live HTTP probe; no ERP/MES writes."""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen


def probe(request, report):
    report["stage"]="start"
    started=time.time()
    progress_seen=False
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(request,"/start",{"text":"连接件A1晚48小时。","case_id":"partial","mode":"live","policy":"adaptive"})
        while not task.done():
            progress=request("/progress")
            progress_seen |= bool(progress and progress["updated_at"]>=started and progress["events"])
            time.sleep(0.3)
        state=task.result()
    report["progress_seen"]=progress_seen
    report["observed_status"]=state.get("status")
    failure=state.get("failure") or {}
    # Do not serialize arbitrary provider error bodies, exception text or headers.
    code=failure.get("error_code") if isinstance(failure,dict) else None
    if code in {"MODEL_QUOTA_EXHAUSTED","MODEL_RATE_LIMITED","MODEL_UNAVAILABLE"}:
        report["failure_code"]=code
    assert state["status"]=="awaiting_approval"
    run_id=state["run_id"]
    report["run_id"]=run_id
    report["stage"]="budget_200"
    state=request("/constraints/budget",{"run_id":run_id,"revision":state["revision"],"budget":200})
    assert state["plans"][1]["summary"]["recovery_cost"]<=200
    assert state["plans"][1]["plan"]["order_outcomes"][0]["late_hours"]==48
    report["stage"]="budget_450"
    state=request("/constraints/budget",{"run_id":run_id,"revision":state["revision"],"budget":450})
    assert state["plans"][1]["summary"]["recovery_cost"]==300
    assert progress_seen and state["approval"] is None and state["drafts"]==[]
    report["stage"]="export"
    evidence=request("/runs/"+run_id+"/evidence")
    report.update(passed=True,stage="complete",budget_changed_outcome=True,evidence=evidence)


def save_probe(output, request):
    """Reserve a new evidence file before requests; failures remain inspectable."""
    output.parent.mkdir(parents=True,exist_ok=True)
    report={"passed":False,"stage":"not_started","progress_seen":False,"external_writes":0}
    with output.open("x",encoding="utf-8") as handle:
        try:
            probe(request, report)
        except Exception as exc:
            report["error_type"]=type(exc).__name__
        finally:
            json.dump(report,handle,ensure_ascii=False,indent=2)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    base="http://127.0.0.1:8766"
    capability=None
    def request(path,payload=None):
        nonlocal capability
        if capability is None:
            with urlopen(base+"/bootstrap",timeout=10) as response: capability=json.load(response)["session_capability"]
        body=json.dumps(payload).encode() if payload is not None else None
        req=Request(base+path,data=body,headers={"Content-Type":"application/json","X-Youjie-Session":capability})
        with urlopen(req,timeout=120) as response: return json.load(response)
    report=save_probe(args.output,request)
    print("HTTP probe passed" if report["passed"] else "HTTP probe failed; evidence saved",report["stage"])
    if not report["passed"]: raise SystemExit(1)


if __name__=="__main__": main()
