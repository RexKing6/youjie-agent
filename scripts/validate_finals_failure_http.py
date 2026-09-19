"""Exercise public diagnostics on the local API; offline and no external writes."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists(): parser.error("Preserve existing evidence")
    rows = []
    def post(path, payload):
        request = urllib.request.Request("http://127.0.0.1:8766" + path,
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)
    for text, case, expected in (("随便聊聊天", "ready", "INPUT_AMBIGUOUS"),
                                 ("A1硬度要95", "ready", "UNSUPPORTED_SCOPE"),
                                 ("A1延期20小时，请核对冲突", "conflict", "EVIDENCE_CONFLICT")):
        code, state = post("/start", {"text": text, "case_id": case, "mode": "offline_rules", "policy": "fixed"})
        diagnostic = state.get("failure", {})
        rows.append({"expected": expected, "http_status": code, "state": state,
                     "passed": code == 200 and diagnostic.get("error_code") == expected
                     and diagnostic.get("external_records") == {"erp": "none", "mes": "none"}})
    code, state = post("/start", {"text": "A1延期20小时", "case_id": "ready", "mode": "offline_rules", "policy": "fixed"})
    status, body = post("/approve", {"run_id": state["run_id"], "revision": state["revision"] + 9,
                                    "actor": "failure-test", "plan_id": state["plans"][0]["plan"]["plan_id"]})
    _, resumed = post("/resume", {"run_id": state["run_id"], "revision": state["revision"]})
    rows.append({"expected": "STALE_APPROVAL", "http_status": status, "response": body,
                 "passed": status == 422 and body.get("failure", {}).get("error_code") == "STALE_APPROVAL"
                 and resumed.get("approval") is None and not resumed.get("execution")})
    report = {"mode": "offline_rules", "no_model_calls": True, "no_external_writes": True,
              "rows": rows, "passed": all(row["passed"] for row in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": report["passed"], "cases": len(rows)}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__": main()
