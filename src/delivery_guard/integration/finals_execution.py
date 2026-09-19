"""Same-run real-test execution and feedback. No tenant or credential from UI."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone

from delivery_guard.hashing import stable_hash
from delivery_guard.finals_failures import failure
from delivery_guard.integration.finals_bridge import (
    validated_plan, physical_allocation, verify_bom, build_erp_command,
    verify_erp_readback, build_mes_command,
)


class FinalsExecution:
    @staticmethod
    def _capacity_record(run_id, action):
        import json, re, subprocess
        from pathlib import Path
        if not re.fullmatch(r"finals_[a-f0-9]{32}", run_id) or action not in {"create", "read"}:
            raise ValueError("INVALID_CAPACITY_SCOPE")
        script=Path(__file__).resolve().parents[3]/"scripts/finals_mes_capacity_event.php"
        result=subprocess.run(["docker","exec","-i","youjie_openmes-backend","php","--",run_id,action],
                              input=script.read_bytes(),capture_output=True,timeout=30,check=True)
        row=json.loads(result.stdout)
        if row.get("run_id")!=run_id or row.get("order_no")!="YOUJIE-CAP-"+run_id[7:] or row.get("line_code")!="YOUJIE-FINALS-LINE":
            raise ValueError("CAPACITY_READBACK_SCOPE_MISMATCH")
        return row

    def inject_capacity(self, engine, run_id, revision, actor, confirmed):
        state=engine._current(run_id,revision)
        if not confirmed or not actor.strip() or state.get("execution") or state.get("capacity_event"):
            raise ValueError("CAPACITY_EVENT_NOT_ALLOWED")
        validated_plan(state,engine.registry)
        old=deepcopy(state["approval"])
        old["valid"]=False
        state.setdefault("history",[]).append({"plans":deepcopy(state["plans"]),"approval":old,"scenario_hash":state["scenario_hash"]})
        state.update(approval=None,drafts=[],plans=[],status="capacity_changed",revision=revision+1)
        state["capacity_event"]={"status":"attempted","actor":actor}
        engine.workflows.pop(run_id,None)
        engine._log(state,"invalidate_approval","手动注入产线占用；停止交付，核对MES排程。")
        self._save(engine,state)
        try:
            self._capacity_record(run_id,"create")
            row=self._capacity_record(run_id,"read")
            epoch=datetime.fromisoformat(self.mapping["epoch"])
            start=(datetime.fromisoformat(row["planned_start_at"])-epoch).total_seconds()/3600
            end=(datetime.fromisoformat(row["planned_end_at"])-epoch).total_seconds()/3600
            if row["status"]!="PENDING" or start!=0 or end!=32:
                raise ValueError("CAPACITY_INTERVAL_MISMATCH")
            state["capacity_event"].update(status="readback_verified",record=row,source_revision=stable_hash(row),start_hour=0,end_hour=32)
            state["capacity_windows"]=[{"start_hour":0,"end_hour":32}]
            engine._log(state,"real_execution_feedback","MES排程回读：产线第0—32小时被其他任务占用，旧方案与批准失效。",event=state["capacity_event"])
        except Exception:
            state["capacity_event"]["status"]="uncertain"
            self._save(engine,state)
            raise ValueError("CAPACITY_WRITE_UNCERTAIN_DELIVERY_BLOCKED") from None
        self._save(engine,state)
        return deepcopy(state)

    def _check_capacity(self,state):
        event=state.get("capacity_event")
        if event and (event.get("status")!="readback_verified" or stable_hash(self._capacity_record(state["run_id"],"read"))!=event.get("source_revision")):
            raise ValueError("MES_CAPACITY_CHANGED_DELIVERY_BLOCKED")

    def replan_capacity(self,engine,run_id,revision):
        state=engine._current(run_id,revision)
        if state["status"]!="capacity_changed" or not state.get("capacity_event"):
            raise ValueError("NO_CAPACITY_CHANGE_TO_REPLAN")
        self._check_capacity(state)
        state["revision"]+=1
        result=engine._solve(state)
        self._save(engine,result)
        return deepcopy(result)

    def demo_progress(self, engine, run_id, revision, actor, confirmed):
        """Human-only test action; real MES persistence followed by normal readback."""
        import json
        import re
        import subprocess
        from pathlib import Path
        state = engine._current(run_id, revision)
        execution = state.get("execution") or {}
        if not confirmed or not actor.strip():
            raise ValueError("OPERATOR_CONFIRMATION_REQUIRED")
        if execution.get("status") != "monitoring" or state.get("status") == "needs_reconciliation":
            raise ValueError("VERIFIED_EXECUTION_REQUIRED")
        name = execution["erp_document"]["name"]
        if not re.fullmatch(r"finals_[a-f0-9]{32}", run_id) or not re.fullmatch(r"MFG-WO-2026-[0-9]+", name):
            raise ValueError("INVALID_TEST_IDENTITY")
        if execution.get("operator_demo"):
            raise ValueError("OPERATOR_EVENT_ALREADY_ATTEMPTED_USE_POLL")
        # Scope/dependency checks before any operator write.
        self._check_erp_dependency(engine, state)
        snapshot = self.mes.execution_snapshot([name])
        rows = snapshot.get("records", [])
        if snapshot.get("missing_order_nos") or len(rows) != 1 or rows[0]["produced_qty"] != 0 or rows[0]["planned_qty"] < 100:
            raise ValueError("OPERATOR_DEMO_REQUIRES_UNSTARTED_ORDER")
        execution["operator_demo"] = {"status": "attempted", "actor": actor, "order_no": name}
        self._save(engine, state)
        script = Path(__file__).resolve().parents[3] / "scripts/finals_mes_operator_event.php"
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", "youjie_openmes-backend", "php", "--", run_id, name],
                input=script.read_bytes(), capture_output=True, timeout=30, check=True)
            receipt = json.loads(result.stdout)
            if receipt.get("run_id") != run_id or receipt.get("order_no") != name:
                raise ValueError("OPERATOR_RECEIPT_MISMATCH")
            execution["operator_demo"].update(status="written", receipt=receipt)
            engine._log(state, "operator_mes_event", "演示操作员在 OpenMES 记录报产100件，等待接口回读。",
                        receipt=receipt, actor=actor)
            self._save(engine, state)
        except Exception:
            execution["operator_demo"]["status"] = "uncertain"
            self._save(engine, state)
            raise ValueError("OPERATOR_WRITE_UNCERTAIN_USE_POLL") from None
        return self.poll(engine, run_id, revision)

    def __init__(self, erp, mes, mapping: dict, persist):
        self.erp,self.mes,self.mapping,self.persist=erp,mes,mapping,persist

    def _save(self,engine,state):
        from delivery_guard.finals_harness import skill_for, harness_view
        for adapter in (self.erp,self.mes):
            receipts=getattr(getattr(adapter,"client",None),"receipts",[])
            while receipts:
                receipt=receipts.pop(0)
                engine._log(state,"execute_tool","测试系统接口已返回，继续核验业务状态",tool=receipt["tool"],
                            skill=skill_for("execution_poll"),mcp=receipt)
        state["harness"]=harness_view(state)
        engine.runs[state["run_id"]]=deepcopy(state)
        self.persist(state)

    def _check_erp_dependency(self,engine,state):
        """Monitor the actual delivered record, including during MES reconciliation."""
        execution=state["execution"]
        baseline=execution["erp_document"]
        fresh=self.erp.client.get_document("Work Order",baseline["name"])
        fields=("name","docstatus","company","production_item","bom_no","qty",
                "source_warehouse","wip_warehouse","fg_warehouse",
                "planned_start_date","planned_end_date","description")
        def projection(doc):
            return {**{k:doc.get(k) for k in fields},"required_items":sorted(
                (r.get("item_code",""),r.get("required_qty",0)) for r in doc.get("required_items",[]))}
        before,after=projection(baseline),projection(fresh)
        if before==after:
            return
        event={"event_id":stable_hash({"run":state["run_id"],"erp_before":before,"erp_after":after}),
               "run_id":state["run_id"],"order_no":baseline["name"],
               "source":"ERPNext_real_test_instance","source_revision":stable_hash(after),
               "invalid_dependency":"ERP_EXECUTION_DEPENDENCY_CHANGED",
               "raw_before":before,"raw_after":after}
        result=engine.execution_feedback(state["run_id"],state["revision"],event)
        result["execution"]["status"]="reconciliation_required"
        result["execution"]["last_error"]={"type":"ValueError","code":"ERP_EXECUTION_DEPENDENCY_CHANGED"}
        result["question"]="ERP工单排程、物料或范围已变化，旧审批失效。须核对原系统记录，不能用MES产量确认跳过。"
        self._save(engine,result)
        raise ValueError("ERP_EXECUTION_DEPENDENCY_CHANGED")

    def execute(self,engine,run_id,revision,actor,confirmed):
        state=engine._current(run_id,revision)
        if confirmed is not True or not actor or not actor.strip():
            raise ValueError("EXPLICIT_TEST_DELIVERY_CONFIRMATION_REQUIRED")
        if state.get("external_followup"):
            raise ValueError("EXISTING_WORK_ORDER_REQUIRES_MANUAL_REMAINING_PLAN_NO_DUPLICATE")
        self._check_capacity(state)
        plan=validated_plan(state,engine.registry)
        allocation=physical_allocation(state,plan)
        execution=state.setdefault("execution", {"status":"not_requested", "approval_hash":stable_hash(state["approval"]),
            "run_id":run_id,"actor":actor,"environment":"test","synthetic_business_data":True})
        if execution["approval_hash"]!=stable_hash(state["approval"]):
            raise ValueError("EXECUTION_APPROVAL_CHANGED")
        if execution["status"] in {"erp_outcome_unknown","mes_outcome_unknown","readback_mismatch"}:
            raise ValueError("RECONCILE_UNKNOWN_REMOTE_RESULT_BEFORE_RETRY")
        if execution["status"]=="monitoring":
            return state
        try:
            if not execution.get("erp_document"):
                boms=self.erp.client.list_documents("BOM",fields=["name"],filters=[["item","=",self.mapping["product"]],["docstatus","=",1]])
                selected=None
                for row in boms:
                    bom=self.erp.client.get_document("BOM",row["name"])
                    try: verify_bom(bom,self.mapping,allocation)
                    except ValueError: continue
                    selected=bom
                    break
                if selected is None:
                    raise ValueError("FINALS_PHYSICAL_BOM_NOT_READY")
                snapshot=self.erp.execution_snapshot()
                cmd=build_erp_command(state,engine.registry,self.mapping,selected,snapshot["source_revision"],datetime.now(timezone.utc).isoformat())
                execution.update(status="erp_outcome_unknown",erp_command=cmd.model_dump(mode="json"),physical_allocation=allocation)
                self._save(engine,state)  # crash after send must not cause blind retransmission
                result=self.erp.execute(cmd)
                execution["erp_result"]=result.model_dump(mode="json")
                names=[r.name for r in result.records if r.doctype=="Work Order"]
                if len(names)!=1: raise ValueError("ERP_WORK_ORDER_CARDINALITY_MISMATCH")
                doc=self.erp.client.get_document("Work Order",names[0])
                verify_erp_readback(doc,state,self.mapping,allocation)
                execution.update(status="erp_verified",erp_document=doc)
                self._save(engine,state)
            doc=execution["erp_document"]
            # Recheck approved material allocation immediately before downstream delivery.
            fresh=self.erp.client.get_document("Work Order",doc["name"])
            verify_erp_readback(fresh,state,self.mapping,allocation)
            before=self.mes.execution_snapshot([doc["name"]])
            if before["records"]:
                raise ValueError("EXISTING_MES_RECORD_REQUIRES_RECONCILIATION")
            cmd=build_mes_command(state,engine.registry,fresh,self.mapping,before["source_revision"],datetime.now(timezone.utc).isoformat())
            execution.update(status="mes_outcome_unknown",mes_command=cmd.model_dump(mode="json"))
            self._save(engine,state)
            result=self.mes.execute(cmd)
            baseline=self.mes.execution_snapshot([doc["name"]])
            if baseline["missing_order_nos"]: raise ValueError("MES_READBACK_MISSING")
            execution.update(status="monitoring",mes_result=result.model_dump(mode="json"),mes_baseline=baseline)
            state["revision"]+=1
            self._save(engine,state)
            return state
        except Exception as exc:
            # If MES was never dispatched, retry can continue from persisted ERP result.
            if execution["status"]=="erp_verified": execution["status"]="partial_failure"
            diagnostic = failure("/integrations/execute", state, exc=exc)
            execution["last_error"]={"type":type(exc).__name__,"code":diagnostic["error_code"]}
            state["failure"] = diagnostic
            self._save(engine,state)
            raise

    def poll(self,engine,run_id,revision):
        state=engine._current(run_id,revision)
        execution=state.get("execution") or {}
        if execution.get("status")!="monitoring": raise ValueError("NO_VERIFIED_EXECUTION_TO_POLL")
        self._check_erp_dependency(engine,state)
        name=execution["erp_document"]["name"]
        after=self.mes.execution_snapshot([name])
        def quarantine(code):
            event={"event_id":stable_hash({"run":run_id,"invalid_snapshot":after,"code":code}),
                   "run_id":run_id,"order_no":name,"source":"OpenMES_real_test_instance",
                   "source_revision":after["source_revision"],"invalid_dependency":code,"raw_after":after}
            result=engine.execution_feedback(run_id,revision,event)
            result["execution"]["status"]="reconciliation_required"
            result["execution"]["last_error"]={"type":"ValueError","code":code}
            result["question"]="真实MES依赖异常，旧审批失效。须先核对原系统记录；不能用产量对账表放行。"
            self._save(engine,result)
            raise ValueError(code)
        if after["missing_order_nos"]: quarantine("MES_WATCHED_RECORD_MISSING")
        before=execution["mes_baseline"]["records"][0]
        row=after["records"][0]
        if (row["planned_qty"]!=before["planned_qty"] or row["product_type_code"]!=before["product_type_code"]
                or row["line_code"]!=before["line_code"]):
            quarantine("MES_EXECUTION_SCOPE_CHANGED_REVIEW_REQUIRED")
        delta=row["produced_qty"]-before["produced_qty"]
        if delta<0: quarantine("MES_PRODUCTION_REGRESSION_REVIEW_REQUIRED")
        if delta!=int(delta): quarantine("MES_FRACTIONAL_QUANTITY_UNSUPPORTED")
        changed=(row["status"],row["produced_qty"])!=(before["status"],before["produced_qty"])
        if not changed:
            state["execution"]["last_poll"]={"changed":False,"source_revision":after["source_revision"]}
            self._save(engine,state)
            return state
        event={"event_id":stable_hash({"run":run_id,"before":before,"after":row}),"run_id":run_id,
               "order_no":name,"source":"OpenMES_real_test_instance","source_revision":after["source_revision"],
               "produced_qty":int(delta),"cumulative_produced_qty":row["produced_qty"],
               "status_before":before["status"],"status_after":row["status"],"raw_after":after}
        result=engine.execution_feedback(run_id,revision,event)
        result["execution"]["last_poll"]={"changed":True,"event_id":event["event_id"]}
        self._save(engine,result)
        return result

    def reconcile(self,engine,run_id,revision):
        """Read-only recovery of uncertain transport; never blindly replay a POST."""
        state=engine._current(run_id,revision)
        execution=state.get("execution") or {}
        plan=validated_plan(state,engine.registry)
        allocation=physical_allocation(state,plan)
        if not execution.get("erp_command"):
            raise ValueError("NO_DISPATCHED_COMMAND_TO_RECONCILE")
        if not execution.get("erp_document"):
            rows=self.erp.client.list_documents("Work Order",fields=["name"],
                filters=[["description","like",f"%run={run_id} %"]])
            if len(rows)!=1:
                raise ValueError("ERP_OUTCOME_UNRESOLVED_NO_BLIND_RETRY")
            doc=self.erp.client.get_document("Work Order",rows[0]["name"])
            verify_erp_readback(doc,state,self.mapping,allocation)
            expected_mrs=[d for d in execution["erp_command"]["payload"]["documents"] if d["doctype"]=="Material Request"]
            mr_rows=self.erp.client.list_documents("Material Request",fields=["name"],
                filters=[["remarks","like",f"%run={run_id} %"]])
            if len(mr_rows)!=len(expected_mrs): raise ValueError("ERP_PURCHASE_RECONCILIATION_REQUIRED")
            for mr,expected in zip(mr_rows,expected_mrs):
                actual=self.erp.client.get_document("Material Request",mr["name"])
                projection=lambda d:sorted((i["item_code"],i["qty"]) for i in d["items"])
                if actual.get("docstatus")!=0 or projection(actual)!=projection(expected):
                    raise ValueError("ERP_PURCHASE_READBACK_MISMATCH")
            execution.update(erp_document=doc,status="erp_verified",recovered_by="read_only_lookup")
        name=execution["erp_document"]["name"]
        snapshot=self.mes.execution_snapshot([name])
        if snapshot["records"]:
            expected=(execution.get("mes_command") or {}).get("payload",{}).get("orders",[])
            if len(expected)!=1: raise ValueError("UNEXPECTED_EXISTING_MES_RECORD")
            row=snapshot["records"][0]
            if any(row.get(k)!=expected[0].get(k) for k in ("planned_qty","line_code","product_type_code")):
                raise ValueError("MES_RECONCILIATION_MISMATCH")
            # Don't swallow production that occurred while the response was uncertain.
            baseline=deepcopy(snapshot)
            baseline["records"][0]["produced_qty"]=0
            baseline["records"][0]["status"]="PENDING"
            execution.update(status="monitoring",mes_baseline=baseline,recovered_by="read_only_lookup")
        elif execution.get("status")=="mes_outcome_unknown":
            raise ValueError("MES_OUTCOME_UNRESOLVED_NO_BLIND_RETRY")
        else:
            execution["status"]="erp_verified"
        execution.pop("last_error",None)
        state["revision"]+=1
        self._save(engine,state)
        return state

    def confirm(self,engine,run_id,revision,confirmation):
        state=engine._current(run_id,revision)
        event=state.get("pending_execution_event") or {}
        if event.get("invalid_dependency"):
            raise ValueError("INVALID_MES_DEPENDENCY_REQUIRES_MANUAL_SOURCE_REVIEW")
        self._check_erp_dependency(engine,state)
        current=self.mes.execution_snapshot([event.get("order_no","")])
        if current["source_revision"]!=event.get("source_revision"):
            raise ValueError("MES_CHANGED_DURING_RECONCILIATION")
        result=engine.confirm_execution_feedback(run_id,revision,confirmation)
        result["execution"]["mes_baseline"]=current
        self._save(engine,result)
        return result
