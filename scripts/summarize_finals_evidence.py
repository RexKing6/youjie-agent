"""Summarize preserved task batches; never hide failed earlier versions."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument("reports",type=Path,nargs="+")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): p.error("Preserve previous summaries")
    batches=[]
    for path in a.reports:
        d=json.loads(path.read_text())
        if not d["complete"]: raise ValueError("Cannot summarize unfinished batch")
        rows=d["rows"]
        batches.append({"report":str(path),"complete":d["complete"],"unchanged":d["unchanged"],
            "tasks":len(rows),"passed":sum(r["passed"] for r in rows),
            "model_calls":sum(r.get("model_calls",0) for r in rows),
            "failed_tasks":[{"id":r["case_id"],"policy":r["policy"],"repeat":r["repeat"],"errors":r["errors"]} for r in rows if not r["passed"]],
            "groups":d["groups"],"scope":d["limitations"]})
    result={"batches":batches,"scope":"Model/task evidence only; not real ERP/MES acceptance. Schema candidate rejection count does not include every semantic misclassification. All failed first attempts preserved. Later use of a heldout case for repair consumes its holdout status."}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":main()
