"""Finals approval-to-physical-record boundary; never fabricate legacy graph state.

Pure builders. Transport, authenticated configuration and persistent execution
ledgers remain in the existing adapters. A2 is never posted as A1 inventory.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from delivery_guard.finals_wiki import compile_wiki, qualify
from delivery_guard.hashing import candidate_plan_hash, stable_hash
from delivery_guard.models import CandidatePlan
from delivery_guard.integration.contracts import CanonicalCommand, IntegrationProfile, TargetSystem


def validated_plan(state: dict, registry: dict) -> dict:
    from delivery_guard.finals_provenance import assert_same_runtime, runtime_provenance
    assert_same_runtime(state,runtime_provenance(registry,state.get("model_name","none")))
    approval = state.get("approval") or {}
    if state.get("status") != "approved_local_drafts" or approval.get("valid") is not True or approval.get("decision") != "approve":
        raise ValueError("VALID_HUMAN_APPROVAL_REQUIRED")
    docs = [registry[i] for i in state["active_documents"]]
    qualification = qualify(state["order"], docs, state["stock"])
    basis = stable_hash({"order":state["order"], "stock":state["stock"],
                         "wiki":compile_wiki(docs)["version"], "qualification":qualification})
    if qualification["gaps"] or basis != state["decision_basis_hash"]:
        raise ValueError("STALE_APPROVAL")
    plans = [p["plan"] for p in state["plans"] if p["plan"]["plan_id"] == approval["plan_id"]]
    if len(plans) != 1:
        raise ValueError("APPROVED_PLAN_MISSING")
    plan = CandidatePlan.model_validate(plans[0])
    if not plan.order_outcomes or not all(outcome.scheduled for outcome in plan.order_outcomes):
        raise ValueError("FULL_ORDER_SCHEDULE_REQUIRED")
    if not plan.evidence or not plan.evidence.verified or plan.evidence.plan_hash != candidate_plan_hash(plan):
        raise ValueError("VERIFIED_PLAN_REQUIRED")
    if candidate_plan_hash(plan) != approval["plan_hash"]:
        raise ValueError("APPROVED_PLAN_HASH_MISMATCH")
    if approval["scenario_hash"] != state["scenario_hash"]:
        raise ValueError("APPROVED_SCENARIO_HASH_MISMATCH")
    # Independently recheck feasibility at the boundary, not merely an evidence flag.
    from delivery_guard.finals_agent import FinalsInvestigation
    from delivery_guard.data import apply_incident
    from delivery_guard.models import Incident
    from delivery_guard.verifier import verify_plan
    scenario=FinalsInvestigation._scenario(state)
    incident=Incident.model_validate({"incident_id":"inc_final_delay","kind":"supplier_delay",
        "target_id":"src_normal","delay_hours":state["order"]["delay_hours"],"description":"模拟A1供应延期"})
    if verify_plan(apply_incident(scenario,incident),plan):
        raise ValueError("INDEPENDENT_PLAN_VERIFICATION_FAILED")
    return plan.model_dump(mode="json")


def physical_allocation(state: dict, plan: dict) -> dict:
    demand = state["order"]["quantity"]
    a1 = min(state["order"]["a1_available"], demand)
    a2 = min(state["qualification"]["eligible_a2"], demand-a1)
    purchase = sum(p["quantity"] for p in plan["purchases"])
    if a1 + a2 + purchase != demand:
        raise ValueError("MATERIAL_CONSERVATION_FAILED")
    return {"a1_existing":a1, "a1_purchase":purchase, "a1_total":a1+purchase,
            "a2":a2, "a2_batch":state["stock"]["batch"], "finished_quantity":demand,
            "qualification_hash":stable_hash(state["qualification"])}


def command(state: dict, profile: IntegrationProfile, payload: dict,
            source_revision: str, created_at: str) -> CanonicalCommand:
    approval = state["approval"]
    identity = stable_hash({"run":state["run_id"], "approval":approval,
                            "basis":state["decision_basis_hash"], "profile":profile.value, "payload":payload})
    is_erp = profile == IntegrationProfile.ERPNEXT
    return CanonicalCommand(command_id="cmd_"+identity[:16], correlation_id="cor_"+state["run_id"],
        causation_id=approval["plan_id"], idempotency_key="sha256:"+identity,
        profile=profile, target_system=TargetSystem.ERPNEXT if is_erp else TargetSystem.OPENMES,
        command_type="ERPNEXT_CREATE_WORK_ORDER_DRAFTS" if is_erp else "OPENMES_IMPORT_APPROVED_WORK_ORDERS",
        environment="test", scenario_hash=state["scenario_hash"], plan_hash=approval["plan_hash"],
        approval_id=approval["approval_id"], expected_source_revision=source_revision,
        created_at=created_at, payload=payload)


def verify_bom(bom: dict, mapping: dict, allocation: dict) -> None:
    if bom.get("docstatus") != 1 or not bom.get("is_active") or bom.get("item") != mapping["product"]:
        raise ValueError("FINALS_SUBMITTED_MATCHING_BOM_REQUIRED")
    quantity = bom.get("quantity", 0)
    if not quantity or quantity <= 0:
        raise ValueError("INVALID_BOM_QUANTITY")
    expected = {mapping["a1"]:allocation["a1_total"], mapping["a2"]:allocation["a2"]}
    actual = {}
    for row in bom.get("items", []):
        code = row["item_code"]
        actual[code] = actual.get(code, 0) + row["qty"] / quantity * allocation["finished_quantity"]
    expected = {k:v for k,v in expected.items() if v}
    if set(actual) != set(expected) or any(abs(actual[k]-v) > 1e-7 for k,v in expected.items()):
        raise ValueError("BOM_PHYSICAL_ALLOCATION_MISMATCH")


def build_erp_command(state: dict, registry: dict, mapping: dict, bom: dict,
                      source_revision: str, created_at: str) -> CanonicalCommand:
    plan = validated_plan(state, registry)
    allocation = physical_allocation(state, plan)
    verify_bom(bom, mapping, allocation)
    if not all(mapping[k].startswith("YOUJIE-FINALS-") for k in ("a1", "a2", "product")):
        raise ValueError("FINALS_NAMESPACE_REQUIRED")
    epoch = datetime.fromisoformat(mapping["epoch"])
    # Frappe Datetime persists local SQL timestamps, not offset-bearing ISO strings.
    def at(hour): return (epoch+timedelta(hours=hour)).strftime('%Y-%m-%d %H:%M:%S')
    tasks = plan["scheduled_operations"]
    description = f"Synthetic finals run={state['run_id']} basis={state['decision_basis_hash']} A2-batch={allocation['a2_batch']}; batch evidence is an application allocation, not ERP stock posting"
    work_order = {"doctype":"Work Order", "docstatus":0, "company":mapping["company"],
        "production_item":mapping["product"], "bom_no":bom["name"], "qty":allocation["finished_quantity"],
        "source_warehouse":mapping["warehouse"], "wip_warehouse":mapping["wip_warehouse"],
        "fg_warehouse":mapping["fg_warehouse"], "use_multi_level_bom":0,
        "planned_start_date":at(min(t["start_hour"] for t in tasks)),
        "planned_end_date":at(max(t["end_hour"] for t in tasks)), "description":description}
    documents = []
    for p in plan["purchases"]:
        if p.get("committed"): continue
        documents.append({"doctype":"Material Request", "docstatus":0, "material_request_type":"Purchase",
            "company":mapping["company"], "transaction_date":at(0)[:10], "schedule_date":at(p["arrival_hour"])[:10],
            "items":[{"item_code":mapping["a1"],"qty":p["quantity"],"warehouse":mapping["warehouse"],
                      "schedule_date":at(p["arrival_hour"])[:10]}], "remarks":description})
    documents.append(work_order)
    return command(state, IntegrationProfile.ERPNEXT,
                   {"documents":documents,"physical_allocation":allocation,"run_id":state["run_id"]}, source_revision, created_at)


def verify_erp_readback(document: dict, state: dict, mapping: dict, allocation: dict) -> None:
    if document.get("docstatus") != 0 or document.get("production_item") != mapping["product"]:
        raise ValueError("ERP_READBACK_IDENTITY_MISMATCH")
    if document.get("qty") != allocation["finished_quantity"] or state["run_id"] not in document.get("description", ""):
        raise ValueError("ERP_READBACK_SCOPE_MISMATCH")
    for field,key in (("company","company"),("source_warehouse","warehouse"),
                      ("wip_warehouse","wip_warehouse"),("fg_warehouse","fg_warehouse")):
        if document.get(field)!=mapping[key]:
            raise ValueError("ERP_READBACK_LOCATION_MISMATCH")
    approved=[p["plan"] for p in state["plans"]
              if p["plan"]["plan_id"]==(state.get("approval") or {}).get("plan_id")]
    if len(approved)!=1:
        raise ValueError("ERP_READBACK_APPROVED_SCHEDULE_MISSING")
    epoch=datetime.fromisoformat(mapping["epoch"])
    tasks=approved[0]["scheduled_operations"]
    for field,hour in (("planned_start_date",min(t["start_hour"] for t in tasks)),
                       ("planned_end_date",max(t["end_hour"] for t in tasks))):
        expected=epoch+timedelta(hours=hour)
        try:
            actual=datetime.fromisoformat(document[field])
            # Frappe's timezone-less Datetime is interpreted in this test mapping's
            # explicit local timezone, never in the host computer's timezone.
            if actual.tzinfo is None:
                actual=actual.replace(tzinfo=epoch.tzinfo)
        except (KeyError,TypeError,ValueError):
            raise ValueError("ERP_READBACK_SCHEDULE_INVALID") from None
        if actual!=expected:
            raise ValueError("ERP_READBACK_SCHEDULE_MISMATCH")
    expected = {mapping["a1"]:allocation["a1_total"], mapping["a2"]:allocation["a2"]}
    actual = {}
    for row in document.get("required_items", []):
        actual[row["item_code"]] = actual.get(row["item_code"], 0) + row["required_qty"]
    expected = {k:v for k,v in expected.items() if v}
    if set(actual) != set(expected) or any(abs(actual[k]-v)>1e-7 for k,v in expected.items()):
        raise ValueError("ERP_READBACK_MATERIAL_MISMATCH")


def build_mes_command(state: dict, registry: dict, erp_document: dict, mapping: dict,
                      source_revision: str, created_at: str) -> CanonicalCommand:
    plan = validated_plan(state, registry)
    allocation = physical_allocation(state, plan)
    verify_erp_readback(erp_document, state, mapping, allocation)
    due = datetime.fromisoformat(mapping["epoch"])+timedelta(hours=12)
    return command(state, IntegrationProfile.OPENMES, {"orders":[{
        "order_no":erp_document["name"], "customer_order_no":state["order"]["order_id"],
        "line_code":mapping["mes_line"], "product_type_code":mapping["mes_product"],
        "planned_qty":allocation["finished_quantity"], "priority":1, "due_date":due.isoformat(),
        "description":f"Synthetic finals run={state['run_id']} ERP={erp_document['name']} basis={state['decision_basis_hash']}"}]},
        source_revision, created_at)


def reconcile_production(state: dict, event: dict, confirmation: dict) -> dict:
    """No automatic deduction from produced_qty to good output or material use."""
    if event.get("run_id") != state["run_id"] or not event.get("event_id"):
        raise ValueError("FEEDBACK_SCOPE_MISMATCH")
    if confirmation.get("event_id") != event["event_id"] or not confirmation.get("actor") or not confirmation.get("evidence_ref"):
        raise ValueError("FEEDBACK_CONFIRMATION_REQUIRED")
    names = ("good_qty", "a1_consumed", "a2_consumed", "elapsed_hours")
    if any(type(confirmation.get(k)) is not int or confirmation[k] < 0 for k in names):
        raise ValueError("FEEDBACK_QUANTITY_INVALID")
    good, a1, a2 = (confirmation[k] for k in names[:3])
    if good != event.get("produced_qty") or good > state["order"]["quantity"]:
        raise ValueError("FEEDBACK_GOOD_QUANTITY_UNSUPPORTED")
    # This narrow no-scrap example cannot silently absorb scrap or rework.
    if a1+a2 != good or a1>state["order"]["a1_available"] or a2>state["qualification"]["eligible_a2"]:
        raise ValueError("FEEDBACK_MATERIAL_CONSERVATION_FAILED")
    return {"event_id":event["event_id"], "completed_good":good,
            "remaining_demand":state["order"]["quantity"]-good,
            "remaining_a1":state["order"]["a1_available"]-a1,
            "remaining_a2_on_hand":state["stock"]["on_hand"]-a2,
            "approval_consumed_a2":a2, "current_hour":confirmation["elapsed_hours"],
            "source":"operator_confirmed_test_reconciliation", "actor":confirmation["actor"],
            "evidence_ref":confirmation["evidence_ref"], "not_mes_native_material_fields":True}
