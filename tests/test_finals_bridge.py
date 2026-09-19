from copy import deepcopy
import pytest
from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.integration.finals_bridge import (
    validated_plan, physical_allocation, verify_bom, build_erp_command,
    build_mes_command, verify_erp_readback, reconcile_production,
)

MAPPING = {"a1":"YOUJIE-FINALS-A1","a2":"YOUJIE-FINALS-A2","product":"YOUJIE-FINALS-PRODUCT",
           "company":"Youjie Demo Manufacturing","warehouse":"Stores - YDM","wip_warehouse":"Work In Progress - YDM",
           "fg_warehouse":"Finished Goods - YDM","epoch":"2026-09-17T08:00:00+08:00",
           "mes_line":"YOUJIE-FINALS-LINE","mes_product":"YOUJIE-FINALS-PRODUCT"}


def approved(quantity=600):
    engine = FinalsInvestigation()
    state = engine.start(f"A1延期24小时，订单需要{quantity}件", case_id="ready")
    state = engine.approve(state["run_id"], state["revision"], state["plans"][0]["plan"]["plan_id"], "test-operator")
    return engine, state


def bom_for(allocation):
    return {"name":"BOM-YOUJIE-FINALS-PRODUCT-001", "item":MAPPING["product"],"docstatus":1,"is_active":1,
            "quantity":allocation["finished_quantity"],"items":[{"item_code":MAPPING[k],"qty":allocation[q]}
            for k,q in (("a1","a1_total"),("a2","a2")) if allocation[q]]}


@pytest.mark.parametrize("quantity", [400,600,800])
def test_real_commands_dynamic_quantities_physical_materials_and_same_run(quantity):
    engine, state = approved(quantity)
    plan = validated_plan(state, engine.registry)
    allocation = physical_allocation(state,plan)
    cmd = build_erp_command(state,engine.registry,MAPPING,bom_for(allocation),"erp-rev","2026-09-17T09:00:00+08:00")
    wo = next(d for d in cmd.payload["documents"] if d["doctype"]=="Work Order")
    assert wo["qty"]==quantity
    assert 'T' not in wo['planned_start_date'] and '+' not in wo['planned_start_date']
    assert len(wo['planned_start_date'])==19
    assert allocation["a1_total"]+allocation["a2"]==quantity
    assert cmd.correlation_id=="cor_"+state["run_id"]
    wo.update(name="MFG-WO-TEST",required_items=[{"item_code":d["item_code"],"required_qty":d["qty"]} for d in bom_for(allocation)["items"]])
    mes = build_mes_command(state,engine.registry,wo,MAPPING,"mes-rev","2026-09-17T09:00:00+08:00")
    assert mes.payload["orders"][0]["planned_qty"]==quantity
    assert mes.payload["orders"][0]["order_no"]==wo["name"]
    assert mes.approval_id==cmd.approval_id
    wo["required_items"][0]["required_qty"] += 1
    with pytest.raises(ValueError,match="MATERIAL"):
        verify_erp_readback(wo,state,MAPPING,allocation)


@pytest.mark.parametrize("attack",["invalid", "stock", "plan", "scope"])
def test_bridge_never_accepts_forged_or_stale_approval(attack):
    engine,state=approved()
    if attack=="invalid": state["approval"]["valid"]=False
    if attack=="stock": state["stock"]["hold"]+=1
    if attack=="plan": state["plans"][0]["plan"]["total_score"]+=1
    if attack=="scope": state["order"]["customer"]="客户甲"
    with pytest.raises(ValueError): validated_plan(state,engine.registry)


def test_wrong_bom_cannot_turn_a2_into_a1():
    engine,state=approved()
    allocation=physical_allocation(state,validated_plan(state,engine.registry))
    bom=bom_for(allocation)
    bom["items"]=[{"item_code":MAPPING["a1"],"qty":600}]
    with pytest.raises(ValueError,match="ALLOCATION"): verify_bom(bom,MAPPING,allocation)


def test_bridge_rejects_unscheduled_plan_even_with_matching_approval_hash():
    engine = FinalsInvestigation()
    state = engine.start("A1延期24小时", case_id="partial")
    scheduled = next(p["plan"] for p in state["plans"] if all(o["scheduled"] for o in p["plan"]["order_outcomes"]))
    state = engine.approve(state["run_id"], state["revision"], scheduled["plan_id"], "test-operator")
    late_state = deepcopy(state)
    late_state["current_hour"] = 95
    state["plans"] = engine._solve(late_state)["plans"]
    unplanned = next(p["plan"] for p in state["plans"] if any(not o["scheduled"] for o in p["plan"]["order_outcomes"]))
    state["approval"]["plan_id"] = unplanned["plan_id"]
    state["approval"]["plan_hash"] = unplanned["evidence"]["plan_hash"]
    with pytest.raises(ValueError, match="FULL_ORDER_SCHEDULE_REQUIRED"):
        validated_plan(state, engine.registry)


@pytest.mark.parametrize("field,value",[("company","wrong"),("source_warehouse","wrong"),
    ("wip_warehouse","wrong"),("fg_warehouse","wrong"),
    ("planned_start_date","2026-09-17T09:00:00+08:00"),
    ("planned_end_date",None),("planned_end_date","not-a-date")])
def test_initial_erp_readback_rejects_wrong_schedule_and_location(field,value):
    engine,state=approved()
    allocation=physical_allocation(state,validated_plan(state,engine.registry))
    bom=bom_for(allocation)
    command=build_erp_command(state,engine.registry,MAPPING,bom,"rev","2026-09-17T08:00:00+08:00")
    wo=deepcopy(command.payload["documents"][-1])
    wo.update(name="MFG-WO-TEST",required_items=[{"item_code":r["item_code"],"required_qty":r["qty"]} for r in bom["items"]])
    wo[field]=value
    with pytest.raises(ValueError,match="ERP_READBACK_(SCHEDULE|LOCATION)"):
        verify_erp_readback(wo,state,MAPPING,allocation)


def test_frappe_naive_schedule_uses_configured_mapping_timezone():
    engine,state=approved()
    allocation=physical_allocation(state,validated_plan(state,engine.registry))
    bom=bom_for(allocation)
    command=build_erp_command(state,engine.registry,MAPPING,bom,"rev","2026-09-17T08:00:00+08:00")
    wo=deepcopy(command.payload["documents"][-1])
    wo.update(name="MFG-WO-TEST",required_items=[{"item_code":r["item_code"],"required_qty":r["qty"]} for r in bom["items"]])
    wo["planned_start_date"]="2026-09-17 08:00:00"
    wo["planned_end_date"]="2026-09-17 12:00:00"
    verify_erp_readback(wo,state,MAPPING,allocation)


def test_real_production_requires_explicit_material_and_quality_reconciliation():
    engine,state=approved()
    event={"run_id":state["run_id"],"event_id":"mes-event-1","produced_qty":100}
    with pytest.raises(ValueError,match="CONFIRMATION"):
        reconcile_production(state,event,{})
    confirmation={"event_id":"mes-event-1","actor":"operator","evidence_ref":"test-confirmation-1",
                  "good_qty":100,"a1_consumed":100,"a2_consumed":0,"elapsed_hours":2}
    result=reconcile_production(state,event,confirmation)
    assert result["remaining_demand"]==500 and result["remaining_a1"]==100
    assert result["remaining_a2_on_hand"]==500
    assert result["not_mes_native_material_fields"]
    bad=deepcopy(confirmation)
    bad["a2_consumed"]=100
    with pytest.raises(ValueError,match="CONSERVATION"): reconcile_production(state,event,bad)
