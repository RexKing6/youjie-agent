"""Loopback-only finals API with explicit approved test-instance delivery."""
from __future__ import annotations

import argparse
import json
import threading
import secrets
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from delivery_guard.finals_agent import CASES, EVIDENCE_BUNDLES, FinalsInvestigation
from delivery_guard.finals_provenance import assert_same_runtime, export_evidence
from delivery_guard.finals_failures import failure, state_failure

ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000"}


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=6000)
    case_id: str = "two_reply"
    policy: Literal["fixed", "adaptive"] = "adaptive"
    mode: Literal["offline_rules", "live"] = "offline_rules"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(max_length=100)
    revision: int = Field(ge=1)


class ReplyRequest(RunRequest):
    text: str = Field(min_length=1, max_length=6000)
    document_ids: list[str] = Field(default_factory=list, max_length=6)


class ApproveRequest(RunRequest):
    plan_id: str = Field(max_length=100)
    actor: str = Field(min_length=1, max_length=80)


class FeedbackRequest(RunRequest):
    hold: int = Field(ge=0, le=500)

class QuarantineRequest(RunRequest):
    quantity: int = Field(ge=1, le=1200)

class BudgetRequest(RunRequest):
    budget: int = Field(ge=0, le=9600)


class ExecuteRequest(RunRequest):
    actor: str = Field(min_length=1,max_length=80)
    confirmed: bool


class ReconcileRequest(RunRequest):
    event_id: str = Field(min_length=1,max_length=100)
    actor: str = Field(min_length=1,max_length=80)
    evidence_ref: str = Field(min_length=1,max_length=500)
    good_qty: int = Field(ge=0,le=1200)
    a1_consumed: int = Field(ge=0,le=1200)
    a2_consumed: int = Field(ge=0,le=500)
    elapsed_hours: int = Field(ge=0,le=95)


class FinalsApplication:
    def __init__(self, live_model=None, store=None, execution=None):
        self.offline = FinalsInvestigation()
        self.live = FinalsInvestigation(model=live_model) if live_model is not None else None
        self.lock = threading.RLock()
        self.store,self.execution=store,execution
        self.session_capability=secrets.token_urlsafe(32)

    def bootstrap(self):
        from copy import deepcopy
        from delivery_guard.finals_harness import SKILLS
        return {"cases": [{"id": k, "label": v["label"]} for k, v in CASES.items()],
                "skills": [{**deepcopy(skill),"status":"pending"} for skill in SKILLS],
                "sources": list(self.offline.registry.values()), "evidence_bundles":EVIDENCE_BUNDLES, "live_enabled": self.live is not None,
                "external_enabled":self.execution is not None, "session_capability":self.session_capability,
                "disclosure": "全部业务数据与文档为模拟；真实测试系统交付须独立确认，未启用时不宣称接通。离线规则不等于在线大模型。",
                "max_replies": None}

    def budget_status(self):
        from delivery_guard.finals_live import BudgetLedger, LEDGER, MAX_CALLS, MAX_MICROYUAN, RESERVE_MICROYUAN
        ledger = getattr(self.live.model, "ledger", None) if self.live else None
        uncapped = bool(getattr(ledger, "uncapped", False))
        state = {"requests": 0, "accounted_microyuan": 0, "uncertain_requests": 0, "halted": False}
        try:
            if ledger is not None:
                state = ledger.snapshot()
            elif LEDGER.exists():
                state = BudgetLedger().snapshot()
        except Exception:
            return {"enabled": self.live is not None, "available": False, "message": "预算状态不可核验；不能据此继续在线调用"}
        return {"enabled": self.live is not None, "available": True, **state,
                "limit_requests": None if uncapped else MAX_CALLS, "limit_cny": None if uncapped else MAX_MICROYUAN / 1_000_000,
                "accounted_cny": state["accounted_microyuan"] / 1_000_000,
                "can_dispatch": self.live is not None and not state["halted"] and (uncapped or (state["requests"] < MAX_CALLS and state["accounted_microyuan"] + RESERVE_MICROYUAN <= MAX_MICROYUAN))}

    def engine_for(self, run_id: str):
        for engine in (self.offline, self.live):
            if engine is not None and run_id in engine.runs:
                return engine
        if self.store is not None:
            state=self.store.load(run_id)
            engine=self.live if state["mode"]=="live" else self.offline
            if engine is None: raise ValueError("原任务在线模式未启用，不能默降离线")
            engine.runs[run_id]=state
            engine.model_attempts[run_id]=state["model_calls"]
            return engine
        raise ValueError("任务不存在或服务已重启，请重新开始")

    def post(self, path: str, payload: dict):
        with self.lock:
            try:
                result=self._post(path,payload)
                if path != "/resume" and isinstance(result, dict) and "run_id" in result:
                    from delivery_guard.finals_harness import harness_view
                    result["harness"]=harness_view(result)
                    self.engine_for(result["run_id"]).runs[result["run_id"]]["harness"]=result["harness"]
                    result["failure"] = state_failure(result)
                    # Mutators return copies: keep the in-memory resume view in
                    # sync with the persisted response, without erasing history.
                    self.engine_for(result["run_id"]).runs[result["run_id"]]["failure"] = result["failure"]
                if path!="/resume" and self.store is not None and isinstance(result,dict) and "run_id" in result:
                    self.store.save(result)
                return result
            except Exception as exc:
                run_id=payload.get("run_id")
                if isinstance(run_id, str):
                    for engine in (self.offline,self.live):
                        if engine is not None and run_id in engine.runs:
                            state = engine.runs[run_id]
                            # Historical runtimes are read-only, including diagnostics.
                            try:
                                assert_same_runtime(state, engine.runtime_provenance)
                            except ValueError:
                                continue
                            diagnostic = self.failure_response(path, payload, exc)["failure"]
                            state["failure"] = diagnostic
                            state.setdefault("failure_history", []).append(diagnostic)
                            if self.store is not None:
                                self.store.save(state)
                raise

    def failure_response(self, path: str, payload: dict, exc: Exception):
        # No arbitrary paths or remote reads merely to explain an error.
        with self.lock:
            run_id = payload.get("run_id")
            state = next((e.runs[run_id] for e in (self.offline, self.live)
                          if e is not None and isinstance(run_id, str) and run_id in e.runs), None)
            wiki_error = (state or {}).get("wiki_refresh_error", {}) if path == "/wiki" else {}
            diagnostic = failure(path, state, exc=exc, code=wiki_error.get("error_code"),
                                 uncertain_without_state=path.startswith(("/integrations/", "/feedback/")))
            return {"message": diagnostic["message"] + "。" + diagnostic["recovery_action"], "failure": diagnostic}

    def evidence(self,run_id: str):
        with self.lock:
            engine=self.engine_for(run_id)
            state=engine.runs[run_id]
            journal=self.store.journal_evidence(run_id) if self.store else None
            return export_evidence(state,engine.runtime_provenance,journal)

    @staticmethod
    def require_current_runtime(engine,run_id):
        assert_same_runtime(engine.runs[run_id],engine.runtime_provenance)

    def _post(self, path: str, payload: dict):
        with self.lock:
            if path in {"/integrations/execute","/integrations/reconcile","/feedback/poll","/feedback/demo-progress","/feedback/capacity","/feedback/capacity-replan","/feedback/confirm","/resume"}:
                cls={"/integrations/execute":ExecuteRequest,"/feedback/demo-progress":ExecuteRequest,"/feedback/capacity":ExecuteRequest,"/feedback/confirm":ReconcileRequest}.get(path,RunRequest)
                req=cls.model_validate(payload)
                engine=self.engine_for(req.run_id)
                if path=="/resume":
                    result=engine._current(req.run_id,engine.runs[req.run_id]["revision"])
                    try:
                        self.require_current_runtime(engine,req.run_id)
                        result["runtime_compatible"]=True
                    except ValueError as exc:
                        result["runtime_compatible"]=False
                        result["resume_warning"]=str(exc)
                    return result
                self.require_current_runtime(engine,req.run_id)
                if self.execution is None: raise ValueError("真实测试系统未配置；不以模拟结果替代")
                if path=="/feedback/capacity": return self.execution.inject_capacity(engine,req.run_id,req.revision,req.actor,req.confirmed)
                if path=="/feedback/capacity-replan": return self.execution.replan_capacity(engine,req.run_id,req.revision)
                if path=="/integrations/execute":
                    return self.execution.execute(engine,req.run_id,req.revision,req.actor,req.confirmed)
                if path=="/integrations/reconcile":
                    return self.execution.reconcile(engine,req.run_id,req.revision)
                if path=="/feedback/poll": return self.execution.poll(engine,req.run_id,req.revision)
                if path=="/feedback/demo-progress": return self.execution.demo_progress(engine,req.run_id,req.revision,req.actor,req.confirmed)
                return self.execution.confirm(engine,req.run_id,req.revision,req.model_dump(exclude={"run_id","revision"}))
            if path == "/start":
                request = StartRequest.model_validate(payload)
                engine = self.live if request.mode == "live" else self.offline
                if engine is None:
                    raise ValueError("真实模型未启用，不会静默切换为离线回放")
                if len(engine.runs) >= 100:
                    raise ValueError("本机演练任务上限已到，请保存记录后重启服务")
                return engine.start(request.text, case_id=request.case_id, policy=request.policy)
            if path == "/compare":
                request = StartRequest.model_validate(payload)
                if request.mode != "offline_rules":
                    raise ValueError("自动对照当前仅开放离线；不隐式启动批量付费调用")
                rows = []
                for policy in ("fixed", "adaptive"):
                    engine = FinalsInvestigation()
                    s = engine.start(request.text, case_id=request.case_id, policy=policy)
                    for reply, documents in (("可以的，王工说没问题", []), ("补充当前订单批准，请核验后计算", ["AP-CURRENT"])):
                        if s["status"] in {"needs_input", "awaiting_evidence"}:
                            s = engine.reply(s["run_id"], s["revision"], reply, documents)
                    rows.append(s)
                return {"runs": rows, "disclosure": "真实执行的离线策略对照；同一输入、相同的两条测试回复与来源、相同规则/求解器。两条回复是本对照样例，不是主流程补证上限；本结果也不是LLM效果评测或真实业务效率证明。"}
            cls = {"/reply": ReplyRequest, "/approve": ApproveRequest, "/feedback": FeedbackRequest,
                   "/feedback/a1-quarantine": QuarantineRequest, "/constraints/budget": BudgetRequest, "/wiki": RunRequest}.get(path)
            if cls is None:
                raise ValueError("不允许的接口")
            request = cls.model_validate(payload)
            engine = self.engine_for(request.run_id)
            self.require_current_runtime(engine,request.run_id)
            if path == "/reply":
                return engine.reply(request.run_id, request.revision, request.text, request.document_ids)
            if path == "/constraints/budget":
                return engine.change_budget(request.run_id, request.revision, request.budget)
            if path == "/approve":
                return engine.approve(request.run_id, request.revision, request.plan_id, request.actor)
            if path == "/feedback":
                return engine.feedback(request.run_id, request.revision, request.hold)
            if path == "/feedback/a1-quarantine":
                return engine.quarantine_a1(request.run_id, request.revision, request.quantity)
            return engine.rebuild_wiki(request.run_id, request.revision)


class FinalsService:
    def __init__(self, port: int = 8766, application: FinalsApplication | None = None):
        self.application = application or FinalsApplication()
        app = self.application
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def allowed(self):
                host = self.headers.get("Host", "").split(":")[0]
                origin = self.headers.get("Origin")
                return host in {"127.0.0.1", "localhost"} and (origin is None or origin in ORIGINS)

            def send_json(self, code, value):
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                if self.headers.get("Origin") in ORIGINS:
                    self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Youjie-Session")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.send_json(200 if self.allowed() else 403, {})

            def do_GET(self):
                if not self.allowed():
                    return self.send_json(403, {"message": "仅限本机允许来源"})
                if self.path == "/health":
                    return self.send_json(200, {"ok": True, "live_enabled": app.live is not None, "external_writes": app.execution is not None})
                if self.path == "/bootstrap":
                    return self.send_json(200, app.bootstrap())
                if self.path == "/budget":
                    return self.send_json(200, app.budget_status())
                if self.path == "/progress":
                    if not secrets.compare_digest(self.headers.get("X-Youjie-Session",""),app.session_capability):
                        return self.send_json(403,{"message":"本机会话已失效"})
                    snapshots=[e.progress for e in (app.offline,app.live) if e is not None and e.progress]
                    return self.send_json(200,max(snapshots,key=lambda p:p["updated_at"]) if snapshots else None)
                match=re.fullmatch(r"/runs/(finals_[a-f0-9]{32})/evidence",self.path)
                if match:
                    if not secrets.compare_digest(self.headers.get("X-Youjie-Session",""),app.session_capability):
                        return self.send_json(403,{"message":"本机会话已失效，请刷新页面后再导出"})
                    try: return self.send_json(200,app.evidence(match[1]))
                    except FileNotFoundError: return self.send_json(404,{"message":"任务不存在"})
                    except ValueError as exc: return self.send_json(422,{"message":str(exc)[:200]})
                    except Exception: return self.send_json(503,{"message":"证据暂时无法完整核验，未导出"})
                self.send_json(404, {"message": "接口不存在"})

            def do_POST(self):
                if not self.allowed():
                    return self.send_json(403, {"message": "仅限本机允许来源"})
                payload = {}
                try:
                    if self.path.startswith(("/integrations/", "/feedback/")) and not secrets.compare_digest(
                            self.headers.get("X-Youjie-Session", ""),app.session_capability):
                        return self.send_json(403,{"message":"本机会话已失效，请刷新页面后再操作"})
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("请求必须为application/json")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32000:
                        raise ValueError("请求长度无效")
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("请求必须为对象")
                    result = app.post(self.path, payload)
                    self.send_json(200, result)
                except ValidationError as exc:
                    self.send_json(422, app.failure_response(self.path, payload if isinstance(payload, dict) else {}, exc))
                except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                    self.send_json(422, app.failure_response(self.path, payload if isinstance(payload, dict) else {}, exc))
                except Exception as exc:
                    self.send_json(503, app.failure_response(self.path, payload if isinstance(payload, dict) else {}, exc))
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--live", action="store_true", help="Use the approved metered model, fail closed on incompatible configuration")
    parser.add_argument("--check-live", action="store_true", help="Validate model configuration without any network request")
    parser.add_argument("--operator-token-plan", action="store_true", help="Explicit local operator interaction with the existing authorized Token Plan")
    parser.add_argument("--erp-credential-file",type=Path)
    parser.add_argument("--mes-credential-file",type=Path)
    parser.add_argument("--integration-mapping",type=Path)
    args = parser.parse_args()
    if args.operator_token_plan and not (args.live or args.check_live):
        parser.error("--operator-token-plan requires --live or --check-live")
    model = None
    if args.live or args.check_live:
        from delivery_guard.finals_live import FinalsLiveModel
        try:
            model = FinalsLiveModel(operator_token_plan=args.operator_token_plan)
        except RuntimeError as exc:
            parser.exit(2, str(exc) + "\n")
        if args.check_live:
            print("Live model configuration validated; no request sent")
            return
    from delivery_guard.integration.finals_state import FinalsStateStore
    root=Path(__file__).resolve().parents[2]
    store=FinalsStateStore(root/".tmp/finals_v2/runs")
    execution=None
    if any((args.erp_credential_file,args.mes_credential_file,args.integration_mapping)):
        if not all((args.erp_credential_file,args.mes_credential_file,args.integration_mapping)):
            parser.error("Both existing credential file paths and integration mapping required")
        from delivery_guard.integration import ERPNextConfig,ERPNextHttpClient,ERPNextAdapter,ERPNextExecutionLedger
        from delivery_guard.integration import OpenMESConfig,OpenMESHttpClient,OpenMESAdapter,OpenMESExecutionLedger
        from delivery_guard.integration.finals_execution import FinalsExecution
        from delivery_guard.finals_mcp import EnterpriseMCPClient
        erp=ERPNextAdapter(EnterpriseMCPClient(ERPNextConfig.from_environment({"DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE":str(args.erp_credential_file)}),args.erp_credential_file,"erp"),
                          ledger=ERPNextExecutionLedger(root/".tmp/erpnext_execution.sqlite3"))
        mes=OpenMESAdapter(EnterpriseMCPClient(OpenMESConfig.from_environment({"DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE":str(args.mes_credential_file)}),args.mes_credential_file,"mes"),
                           ledger=OpenMESExecutionLedger(root/".tmp/openmes_execution.sqlite3"))
        execution=FinalsExecution(erp,mes,json.loads(args.integration_mapping.read_text()),store.save)
    service = FinalsService(args.port, FinalsApplication(live_model=model,store=store,execution=execution))
    print(f"Finals local evidence API: http://127.0.0.1:{args.port}; live_enabled={model is not None}; test_delivery_enabled={execution is not None}")
    try:
        service.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.server.server_close()


if __name__ == "__main__":
    main()
