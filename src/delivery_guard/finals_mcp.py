"""Local MCP 2025-03-26 stdio tools, with no model-selected network/file access.

Business snapshots are supplied by the trusted Harness, not by the model. The
model selects only tool names; scoped document bodies remain untrusted data.
"""
from __future__ import annotations
import json
import subprocess
import selectors
import sys
import time
from copy import deepcopy
from pydantic import BaseModel, ConfigDict

PROTOCOL="2025-03-26"
MAX_BYTES=4_000_000
ENTERPRISE = {
    "erp_health":[], "erp_list":["doctype","fields","filters","limit"],
    "erp_read":["doctype","name"], "erp_create_draft":["doctype","document"],
    "mes_health":[], "mes_read":["order_nos"], "mes_import":["orders"],
}


class Snapshot(BaseModel):
    model_config=ConfigDict(extra="forbid")
    order: dict
    stock: dict
    documents: list[dict]


DESCRIPTIONS={"query_order":"查询本任务的订单与BOM用量快照（模拟业务）",
 "retrieve_authorization":"检索本任务获准访问的历史/当前证明并返回原文",
 "query_quality_stock":"查询质量证明与库存快照；不代表现场盘点",
 "query_delivery":"调查模拟合格来源的报价与到货时间",
 "solve_recovery":"CP-SAT恢复排程和独立约束校验"}


def catalog():
    return [{"name":name,"description":desc,"inputSchema": Snapshot.model_json_schema() if name!="solve_recovery" else
             {"type":"object","properties":{"scenario":{"type":"object"},"incident":{"type":"object"}},"required":["scenario","incident"],"additionalProperties":False}}
            for name,desc in DESCRIPTIONS.items()] + [
                {"name":name,"description":"真实本机测试实例接口；写入须Harness审批及适配器幂等守卫", "inputSchema":{
                    "type":"object","properties":{k:{} for k in keys},"additionalProperties":False}}
                for name,keys in ENTERPRISE.items()]


def enterprise_execute(name, args, erp_path, mes_path):
    if not isinstance(args,dict) or set(args)-set(ENTERPRISE[name]): raise ValueError("INVALID_ARGUMENTS")
    if name.startswith("erp_"):
        if not erp_path: raise ValueError("ERP_NOT_CONFIGURED")
        from delivery_guard.integration.erpnext import ERPNextConfig, ERPNextHttpClient
        client=ERPNextHttpClient(ERPNextConfig.from_environment({"DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE":erp_path}))
        if name=="erp_health": return client.health()
        if name=="erp_list": return client.list_documents(**args)
        if name=="erp_read": return client.get_document(**args)
        return client.create_draft(**args).model_dump(mode="json")
    if not mes_path: raise ValueError("MES_NOT_CONFIGURED")
    from delivery_guard.integration.openmes import OpenMESConfig, OpenMESHttpClient
    client=OpenMESHttpClient(OpenMESConfig.from_environment({"DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE":mes_path}))
    if name=="mes_health": return client.health()
    if name=="mes_read": return client.work_order_snapshot(**args)
    return client.import_work_orders(**args)


def execute(name, arguments):
    if name not in DESCRIPTIONS: raise ValueError("UNKNOWN_TOOL")
    if name=="solve_recovery":
        if set(arguments)!={"scenario","incident"}: raise ValueError("INVALID_SOLVER_ARGUMENTS")
        from delivery_guard.models import Scenario, Incident
        from delivery_guard.workflow import RecoveryWorkflow
        from delivery_guard.diagnostics import summarize_plan
        workflow=RecoveryWorkflow(Scenario.model_validate(arguments["scenario"]),Incident.model_validate(arguments["incident"]))
        workflow.analyze()
        workflow.solve(objective_mode="lexicographic")
        return {"scenario_hash":workflow.scenario_hash,"plans":[{"plan":p.model_dump(mode="json"),
            "summary":summarize_plan(workflow.adjusted_scenario,p)} for p in workflow.plans]}
    ctx=Snapshot.model_validate(arguments)
    if name=="query_order": return deepcopy(ctx.order)
    if name=="retrieve_authorization":
        docs=[d for d in ctx.documents if d["role"]!="quality_authority"]
        return {"sources":[d["id"] for d in docs],"documents":docs,"scope":"current order plus distinct historical context","synthetic":True}
    if name=="query_quality_stock":
        return {"stock":ctx.stock,"sources":[d["id"] for d in ctx.documents if d["role"]=="quality_authority"],"synthetic":True}
    return {"normal_arrival_hour":8+ctx.order["delay_hours"],"emergency_arrival_hour":8,"emergency_unit_cost_cny":8,
            "regional_arrival_hour":24,"regional_unit_cost_cny":3,"synthetic":True,
            "offers":[{"source":"原供应商","arrival_hour":8+ctx.order["delay_hours"],"incremental_unit_cost":0},
                      {"source":"区域调拨","arrival_hour":24,"incremental_unit_cost":3},
                      {"source":"应急来源","arrival_hour":8,"incremental_unit_cost":8}]}


def serve(erp_path=None, mes_path=None):
    initialized=False
    negotiated=False
    for line in sys.stdin.buffer:
        msg={}
        try:
            if len(line)>MAX_BYTES: raise ValueError("PAYLOAD_TOO_LARGE")
            msg=json.loads(line)
            if not isinstance(msg,dict) or msg.get("jsonrpc")!="2.0": raise ValueError("INVALID_REQUEST")
            method=msg.get("method")
            if method=="initialize":
                negotiated=True
                result={"protocolVersion":PROTOCOL,"capabilities":{"tools":{}},"serverInfo":{"name":"youjie-local-tools","version":"1.0"}}
            elif method=="notifications/initialized" and negotiated:
                initialized=True
                continue
            elif not initialized: raise ValueError("INITIALIZE_REQUIRED")
            elif method=="ping": result={}
            elif method=="tools/list": result={"tools":catalog()}
            elif method=="tools/call":
                params=msg.get("params",{})
                try:
                    name=params["name"]
                    data=enterprise_execute(name,params.get("arguments",{}),erp_path,mes_path) if name in ENTERPRISE else execute(name,params.get("arguments",{}))
                    result={"content":[{"type":"text","text":json.dumps(data,ensure_ascii=False)}],"isError":False}
                except Exception:
                    result={"content":[{"type":"text","text":"TOOL_EXECUTION_REJECTED"}],"isError":True}
            else: raise ValueError("METHOD_NOT_FOUND")
            response={"jsonrpc":"2.0","id":msg.get("id"),"result":result}
        except Exception:
            response={"jsonrpc":"2.0","id":msg.get("id") if isinstance(msg,dict) else None,
                      "error":{"code":-32600,"message":"INVALID_MCP_REQUEST"}}
        if isinstance(msg,dict) and "id" in msg:
            print(json.dumps(response,ensure_ascii=False),flush=True)


def call_tool(name, arguments, *, timeout=45, erp_path=None, mes_path=None):
    """Actual child process transport; no shell and no secret environment export."""
    from delivery_guard.hashing import stable_hash
    messages=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":PROTOCOL,"capabilities":{},"clientInfo":{"name":"youjie-harness","version":"1.0"}}},
              {"jsonrpc":"2.0","method":"notifications/initialized"},
              {"jsonrpc":"2.0","id":2,"method":"tools/list"},
              {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":name,"arguments":arguments}}]
    payload="\n".join(json.dumps(m,ensure_ascii=False) for m in messages)+"\n"
    if len(payload.encode())>MAX_BYTES: raise ValueError("MCP_PAYLOAD_TOO_LARGE")
    start=time.monotonic()
    command=[sys.executable,"-m","delivery_guard.finals_mcp"]
    if erp_path: command += ["--erp-credential-file",str(erp_path)]
    if mes_path: command += ["--mes-credential-file",str(mes_path)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    rows=[]
    try:
        for msg in messages:
            proc.stdin.write((json.dumps(msg,ensure_ascii=False)+"\n").encode())
            proc.stdin.flush()
            if "id" not in msg: continue
            with selectors.DefaultSelector() as sel:
                sel.register(proc.stdout,selectors.EVENT_READ)
                if not sel.select(max(0,timeout-(time.monotonic()-start))): raise TimeoutError("MCP_TIMEOUT")
            raw=proc.stdout.readline(MAX_BYTES+1)
            if not raw or len(raw)>MAX_BYTES: raise ValueError("MCP_INVALID_RESPONSE")
            row=json.loads(raw)
            if row.get("id")!=msg["id"] or "error" in row: raise ValueError("MCP_INVALID_RESPONSE")
            if msg["id"]==1 and row["result"].get("protocolVersion")!=PROTOCOL: raise ValueError("MCP_PROTOCOL_MISMATCH")
            if msg["id"]==2 and name not in {t["name"] for t in row["result"]["tools"]}: raise ValueError("MCP_TOOL_NOT_ADVERTISED")
            rows.append(row)
    finally:
        proc.stdin.close()
        if proc.poll() is None: proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    if len(rows)!=3 or [r.get("id") for r in rows]!=[1,2,3] or any("error" in r for r in rows):
        raise ValueError("MCP_INVALID_RESPONSE")
    if rows[0]["result"]["protocolVersion"]!=PROTOCOL: raise ValueError("MCP_PROTOCOL_MISMATCH")
    if name not in {t["name"] for t in rows[1]["result"]["tools"]}: raise ValueError("MCP_TOOL_NOT_ADVERTISED")
    result=rows[2]["result"]
    if result.get("isError"): raise ValueError("MCP_TOOL_REJECTED")
    data=json.loads(result["content"][0]["text"])
    return data,{"transport":"stdio","protocol":PROTOCOL,"server":"youjie-local-tools", "method":"tools/call",
                 "tool":name,"request_sha256":stable_hash(messages[-1]),"response_sha256":stable_hash(rows[-1]),
                 "duration_ms":round((time.monotonic()-start)*1000),"lifecycle":["initialize","notifications/initialized","tools/list","tools/call"]}


class EnterpriseMCPClient:
    """Trusted adapter-side proxy. Model catalog does not grant write access."""
    def __init__(self, config, credential_path, system):
        self.config,self.credential_path,self.system=config,credential_path,system
        self.receipts=[]

    def _call(self,name,args):
        data,receipt=call_tool(name,args,**{f"{self.system}_path":self.credential_path})
        self.receipts.append(receipt)
        return data

    def health(self): return self._call(self.system+"_health",{})
    def list_documents(self,doctype,*,fields=None,filters=None,limit=100):
        return self._call("erp_list",{"doctype":doctype,"fields":fields,"filters":filters,"limit":limit})
    def get_document(self,doctype,name): return self._call("erp_read",{"doctype":doctype,"name":name})
    def create_draft(self,doctype,document):
        from delivery_guard.integration.erpnext import ERPNextCreatedRecord
        return ERPNextCreatedRecord.model_validate(self._call("erp_create_draft",{"doctype":doctype,"document":document}))
    def work_order_snapshot(self,order_nos): return self._call("mes_read",{"order_nos":order_nos})
    def import_work_orders(self,orders): return self._call("mes_import",{"orders":orders})


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--erp-credential-file")
    parser.add_argument("--mes-credential-file")
    opts=parser.parse_args()
    serve(opts.erp_credential_file,opts.mes_credential_file)
