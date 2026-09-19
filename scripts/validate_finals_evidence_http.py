"""Exercise the running loopback API and protected evidence export; no ERP writes."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error("Preserve prior evidence")
    base="http://127.0.0.1:8766"
    def request(path,payload=None,session=None):
        headers={"Content-Type":"application/json"}
        if session: headers["X-Youjie-Session"]=session
        req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        return json.load(urllib.request.urlopen(req,timeout=120))
    bootstrap=request("/bootstrap")
    state=request("/start",{"text":"A1延期28小时，需要420件，请核对后排程。","case_id":"ready","policy":"adaptive","mode":"live"})
    assert state["status"]=="awaiting_approval" and state["order"]["quantity"]==420 and state["order"]["delay_hours"]==28
    identity={"run_id":state["run_id"],"revision":state["revision"]}
    state=request("/wiki",identity)
    assert state["wiki"]["mode"]=="live"
    identity={"run_id":state["run_id"],"revision":state["revision"]}
    state=request("/approve",{**identity,"plan_id":state["plans"][0]["plan"]["plan_id"],"actor":"HTTP local verification"})
    endpoint=f"/runs/{state['run_id']}/evidence"
    denied=False
    try: request(endpoint)
    except urllib.error.HTTPError as exc: denied=exc.code==403
    assert denied
    evidence=request(endpoint,session=bootstrap["session_capability"])
    assert evidence["runtime_compatible"] and evidence["journal"]["chain_valid"]
    assert evidence["journal"]["entries"]>=3
    assert evidence["state"]["runtime_provenance"]["runtime_hash"]
    assert evidence["state"]["model_request_provenance"]
    assert not evidence["state"].get("execution")
    result={"passed":True,"no_external_writes":True,"unauthenticated_export_denied":denied,"evidence":evidence}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({"passed":True,"run_id":state["run_id"],"mode":state["mode"],"quantity":420,"external_writes":0}))


if __name__=="__main__":main()
