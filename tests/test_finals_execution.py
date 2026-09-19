from copy import deepcopy
from types import SimpleNamespace
import pytest
from delivery_guard.integration.finals_execution import FinalsExecution
from delivery_guard.integration.finals_state import FinalsStateStore
from delivery_guard.integration.finals_bridge import physical_allocation,validated_plan
from test_finals_bridge import approved,bom_for,MAPPING


class Result:
    def __init__(self,records): self.records=records
    def model_dump(self,**kwargs): return {"records":[vars(x) for x in self.records]}


@pytest.mark.parametrize('confirmed', [False, True])
def test_operator_demo_requires_confirmation_and_delivery(tmp_path, monkeypatch, confirmed):
    engine,state,service,*_=runtime(tmp_path)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('must not write'))
    with pytest.raises(ValueError):
        service.demo_progress(engine,state['run_id'],state['revision'],'operator',confirmed)


def test_operator_demo_real_readback_and_duplicate_guard(tmp_path, monkeypatch):
    import json
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state['run_id'],state['revision'],'operator',True)
    name='MFG-WO-2026-99999'
    erp.doc['name']=name
    state['execution']['erp_document']['name']=name
    mes.row['order_no']=name
    service._save(engine,state)
    calls=[]
    def operator(*args,**kwargs):
        calls.append(args)
        mes.row.update(produced_qty=100,status='IN_PROGRESS')
        return SimpleNamespace(stdout=json.dumps({'run_id':state['run_id'],'order_no':name}).encode())
    monkeypatch.setattr('subprocess.run',operator)
    result=service.demo_progress(engine,state['run_id'],state['revision'],'operator',True)
    assert result['approval'] is None and result['status']=='needs_reconciliation'
    assert result['pending_execution_event']['produced_qty']==100
    with pytest.raises(ValueError):
        service.demo_progress(engine,result['run_id'],result['revision'],'operator',True)
    assert len(calls)==1 and erp.writes==mes.writes==1


def runtime(tmp_path):
    engine,state=approved()
    allocation=physical_allocation(state,validated_plan(state,engine.registry))
    bom=bom_for(allocation)
    class ERP:
        client=None
        writes=0
        doc=None
        def list_documents(self,*a,**k): return [{"name":bom["name"]}]
        def get_document(self,doctype,name): return deepcopy(bom if doctype=="BOM" else self.doc)
        def execution_snapshot(self): return {"source_revision":"erp-before"}
        def execute(self,command):
            self.writes+=1
            self.doc=deepcopy(command.payload["documents"][-1])
            self.doc.update(name="MFG-WO-FINALS-TEST",required_items=[{"item_code":r["item_code"],"required_qty":r["qty"]} for r in bom["items"]])
            return Result([SimpleNamespace(name=self.doc["name"],doctype="Work Order")])
    class MES:
        writes=0
        row=None
        revision=0
        def execution_snapshot(self,names):
            return {"source_revision":f"mes-{self.revision}","records":[deepcopy(self.row)] if self.row else [],
                    "missing_order_nos":[] if self.row else names}
        def execute(self,command):
            self.writes+=1
            d=command.payload["orders"][0]
            self.row={**d,"produced_qty":0,"status":"PENDING"}
            self.revision+=1
            return Result([])
    erp,mes=ERP(),MES()
    erp.client=erp
    store=FinalsStateStore(tmp_path)
    service=FinalsExecution(erp,mes,MAPPING,store.save)
    return engine,state,service,erp,mes,store


def test_execute_idempotent_and_real_feedback_same_run(tmp_path):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    assert state["execution"]["status"]=="monitoring"
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    assert erp.writes==mes.writes==1
    assert store.load(state["run_id"])["execution"]["erp_document"]["name"]==erp.doc["name"]
    mes.row.update(produced_qty=100,status="IN_PROGRESS")
    mes.revision+=1
    state=service.poll(engine,state["run_id"],state["revision"])
    assert state["status"]=="needs_reconciliation" and state["approval"] is None
    assert not state["history"][-1]["approval"]["valid"]
    event=state["pending_execution_event"]
    confirmation={"event_id":event["event_id"],"actor":"tester","evidence_ref":"manual-test-confirmation",
                  "good_qty":100,"a1_consumed":100,"a2_consumed":0,"elapsed_hours":2}
    state=service.confirm(engine,state["run_id"],state["revision"],confirmation)
    assert state["order"]["quantity"]==500 and state["order"]["a1_available"]==100
    assert state["status"]=="awaiting_approval" and state["completed_good"]==100
    assert all(t["start_hour"]>=2 for p in state["plans"] for t in p["plan"]["scheduled_operations"])
    with pytest.raises(ValueError,match="NO_DUPLICATE"):
        service.execute(engine,state["run_id"],state["revision"],"operator",True)
    assert erp.writes==mes.writes==1


def test_no_confirmation_no_write(tmp_path):
    engine,state,service,erp,mes,_=runtime(tmp_path)
    with pytest.raises(ValueError,match="CONFIRMATION"):
        service.execute(engine,state["run_id"],state["revision"],"operator",False)
    assert erp.writes==mes.writes==0


def test_positive_production_regression_after_confirmation_is_quarantined(tmp_path):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    mes.row.update(produced_qty=100,status="IN_PROGRESS")
    mes.revision+=1
    state=service.poll(engine,state["run_id"],state["revision"])
    event=state["pending_execution_event"]
    state=service.confirm(engine,state["run_id"],state["revision"],{
        "event_id":event["event_id"],"actor":"tester","evidence_ref":"test-only",
        "good_qty":100,"a1_consumed":100,"a2_consumed":0,"elapsed_hours":2})
    mes.row["produced_qty"]=50
    mes.revision+=1
    with pytest.raises(ValueError,match="PRODUCTION_REGRESSION"):
        service.poll(engine,state["run_id"],state["revision"])
    saved=store.load(state["run_id"])
    assert saved["completed_good"]==100 and saved["order"]["quantity"]==500
    assert saved["execution"]["status"]=="reconciliation_required"
    assert saved["approval"] is None and erp.writes==mes.writes==1


@pytest.mark.parametrize("field,value",[("planned_start_date","2099-01-01"),("qty",599),("bom_no","wrong-bom")])
def test_erp_changes_invalidate_even_when_mes_unchanged(tmp_path,field,value):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    erp.doc[field]=value
    with pytest.raises(ValueError,match="ERP_EXECUTION_DEPENDENCY_CHANGED"):
        service.poll(engine,state["run_id"],state["revision"])
    saved=store.load(state["run_id"])
    assert saved["approval"] is None
    assert saved["execution"]["status"]=="reconciliation_required"
    assert saved["pending_execution_event"]["source"]=="ERPNext_real_test_instance"
    assert erp.writes==mes.writes==1


def test_erp_edit_between_poll_and_confirmation_cannot_release(tmp_path):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    mes.row.update(produced_qty=100,status="IN_PROGRESS")
    mes.revision+=1
    state=service.poll(engine,state["run_id"],state["revision"])
    event=state["pending_execution_event"]
    erp.doc["required_items"][0]["required_qty"]+=1
    confirmation={"event_id":event["event_id"],"actor":"tester","evidence_ref":"test",
                  "good_qty":100,"a1_consumed":100,"a2_consumed":0,"elapsed_hours":2}
    with pytest.raises(ValueError,match="ERP_EXECUTION_DEPENDENCY_CHANGED"):
        service.confirm(engine,state["run_id"],state["revision"],confirmation)
    saved=store.load(state["run_id"])
    assert not saved.get("completed_good",0)
    assert saved["execution"]["status"]=="reconciliation_required"
    assert saved["history"][-1]["superseded_pending_event"]["event_id"]==event["event_id"]


def test_state_paths_and_integrity(tmp_path):
    store=FinalsStateStore(tmp_path)
    with pytest.raises(ValueError): store.load("../secrets")
    _,state=approved()
    store.save(state)
    path=store.path(state["run_id"])
    path.write_text(path.read_text().replace('"revision": 2','"revision": 999'))
    with pytest.raises(ValueError,match="INTEGRITY"): store.load(state["run_id"])


def test_pending_plan_can_be_approved_after_process_restart(tmp_path):
    from delivery_guard.finals_api import FinalsApplication
    from delivery_guard.finals_agent import FinalsInvestigation
    engine=FinalsInvestigation()
    state=engine.start("A1延期24小时，订单需要600件",case_id="ready")
    store=FinalsStateStore(tmp_path)
    store.save(state)
    restarted=FinalsApplication(store=store)
    restored=restarted.engine_for(state["run_id"])
    result=restored.approve(state["run_id"],state["revision"],state["plans"][0]["plan"]["plan_id"],"operator")
    assert result["status"]=="approved_local_drafts"
    validated_plan(result,restored.registry)


def test_mes_failure_keeps_erp_and_never_blindly_replays(tmp_path):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    original=mes.execute
    def uncertain(command):
        original(command)
        raise TimeoutError("simulated response lost after apply")
    mes.execute=uncertain
    with pytest.raises(TimeoutError):
        service.execute(engine,state["run_id"],state["revision"],"operator",True)
    saved=store.load(state["run_id"])
    assert saved["execution"]["status"]=="mes_outcome_unknown"
    assert saved["execution"]["erp_document"]["name"]==erp.doc["name"]
    with pytest.raises(ValueError,match="UNKNOWN_REMOTE"):
        service.execute(engine,state["run_id"],saved["revision"],"operator",True)
    recovered=service.reconcile(engine,state["run_id"],saved["revision"])
    assert recovered["execution"]["status"]=="monitoring"
    assert erp.writes==mes.writes==1


def test_feedback_duplicate_no_double_consumption_and_changed_confirmation_blocked(tmp_path):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    unchanged=service.poll(engine,state["run_id"],state["revision"])
    assert unchanged["approval"]["valid"]
    mes.row.update(produced_qty=100,status="IN_PROGRESS")
    mes.revision+=1
    changed=service.poll(engine,state["run_id"],state["revision"])
    repeated=service.poll(engine,state["run_id"],changed["revision"])
    assert repeated["revision"]==changed["revision"]
    assert len(repeated["seen_execution_events"])==1
    event=repeated["pending_execution_event"]
    confirmation={"event_id":event["event_id"],"actor":"tester","evidence_ref":"test",
                  "good_qty":100,"a1_consumed":100,"a2_consumed":0,"elapsed_hours":2}
    mes.revision+=1
    with pytest.raises(ValueError,match="CHANGED_DURING"):
        service.confirm(engine,state["run_id"],repeated["revision"],confirmation)
    assert not engine.runs[state["run_id"]].get("completed_good",0)


@pytest.mark.parametrize("change",["missing","quantity","regression","fractional"])
def test_invalid_external_state_also_invalidates_old_approval(tmp_path,change):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    state=service.execute(engine,state["run_id"],state["revision"],"operator",True)
    if change=="missing": mes.row=None
    elif change=="quantity": mes.row["planned_qty"]+=1
    elif change=="regression": mes.row["produced_qty"]=-1
    else: mes.row["produced_qty"]=0.5
    mes.revision+=1
    with pytest.raises(ValueError): service.poll(engine,state["run_id"],state["revision"])
    saved=store.load(state["run_id"])
    assert saved["approval"] is None
    assert saved["status"]=="needs_reconciliation"
    assert saved["execution"]["status"]=="reconciliation_required"
    assert erp.writes==mes.writes==1
def test_pre_delivery_capacity_invalidates_replans_and_rechecks(tmp_path, monkeypatch):
    from delivery_guard.hashing import stable_hash
    engine,state,service,erp,mes,store=runtime(tmp_path)
    service.mapping['epoch']='2026-09-17T08:00:00+08:00'
    row={'run_id':state['run_id'],'order_no':'YOUJIE-CAP-'+state['run_id'][7:],
         'line_code':'YOUJIE-FINALS-LINE','status':'PENDING',
         'planned_start_at':'2026-09-17T00:00:00+00:00','planned_end_at':'2026-09-18T08:00:00+00:00'}
    calls=[]
    def record(run_id,action):
        calls.append(action)
        return deepcopy(row)
    monkeypatch.setattr(service,'_capacity_record',record)
    changed=service.inject_capacity(engine,state['run_id'],state['revision'],'operator',True)
    assert calls==['create','read']
    assert changed['status']=='capacity_changed' and changed['approval'] is None and not changed['plans']
    assert erp.writes==mes.writes==0
    with pytest.raises(ValueError):
        service.execute(engine,changed['run_id'],changed['revision'],'operator',True)
    new=service.replan_capacity(engine,changed['run_id'],changed['revision'])
    assert new['status']=='awaiting_approval' and new['approval'] is None
    assert all(p['plan']['order_outcomes'][0]['completion_hour']>=36 for p in new['plans'])
    assert new['capacity_event']['source_revision']==stable_hash(row)
    with pytest.raises(ValueError):
        service.inject_capacity(engine,new['run_id'],new['revision'],'operator',True)
    new=engine.approve(new['run_id'],new['revision'],new['plans'][0]['plan']['plan_id'],'operator')
    delivered=service.execute(engine,new['run_id'],new['revision'],'operator',True)
    assert delivered['execution']['status']=='monitoring'
    assert erp.writes==mes.writes==1
    row['planned_end_at']='2026-09-19T00:00:00+00:00'
    with pytest.raises(ValueError,match='MES_CAPACITY_CHANGED'):
        service._check_capacity(new)

def test_capacity_failed_write_blocks_delivery_without_retry(tmp_path,monkeypatch):
    engine,state,service,erp,mes,store=runtime(tmp_path)
    def fail(*args): raise RuntimeError('uncertain')
    monkeypatch.setattr(service,'_capacity_record',fail)
    with pytest.raises(ValueError,match='CAPACITY_WRITE_UNCERTAIN'):
        service.inject_capacity(engine,state['run_id'],state['revision'],'operator',True)
    stored=engine.runs[state['run_id']]
    assert stored['approval'] is None and stored['capacity_event']['status']=='uncertain'
    with pytest.raises(ValueError):
        service.execute(engine,stored['run_id'],stored['revision'],'operator',True)
    assert erp.writes==mes.writes==0
