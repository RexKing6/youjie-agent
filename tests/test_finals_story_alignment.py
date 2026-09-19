import pytest
from delivery_guard.finals_agent import FinalsInvestigation, rule_interpret
from delivery_guard.finals_api import FinalsApplication
from delivery_guard.integration.finals_bridge import physical_allocation, validated_plan


def ready(engine, delay=48, quantity=600):
    s = engine.start(f"A1延期{delay}小时，订单X需要{quantity}件", case_id="guided")
    s = engine.reply(s["run_id"], s["revision"], "以前用过A2，王工说应该可以", [])
    assert s["status"] == "awaiting_evidence" and not s["plans"]
    return engine.reply(s["run_id"], s["revision"], "提供本订单技术确认和300个A2批准", ["AP-PARTIAL", "TECH-CURRENT"])


def test_three_real_solver_channels_match_story():
    e = FinalsInvestigation()
    s = ready(e)
    assert s["status"] == "awaiting_approval"
    expected = [(800, 12, 0, "src_emergency"), (300, 28, 16, "src_regional"), (0, 60, 48, "src_normal")]
    for row, (cost, end, late, source) in zip(s["plans"], expected):
        p = row["plan"]
        assert row["summary"]["recovery_cost"] == cost
        assert p["order_outcomes"][0]["completion_hour"] == end
        assert p["order_outcomes"][0]["late_hours"] == late
        assert p["evidence"]["verified"]
        assert [(a["source_id"], a["quantity"]) for a in p["purchases"]] == [(source, 100)]
        assert physical_allocation(s, p)["a1_total"] == 300
    assert s["knowledge_updates"][-1]["document_ids"] == ["AP-PARTIAL", "TECH-CURRENT"]
    assert s["knowledge_updates"][-1]["version"] == s["wiki"]["version"]
    approved = e.approve(s["run_id"], s["revision"], s["plans"][1]["plan"]["plan_id"], "test")
    validated_plan(approved, e.registry)


def test_quarantine_invalidates_then_recalculates_without_overspending():
    e = FinalsInvestigation()
    s = ready(e)
    old = e.approve(s["run_id"], s["revision"], s["plans"][1]["plan"]["plan_id"], "test")
    # Persisted tasks can have no in-memory workflow after server restart.
    e.workflows.clear()
    s = e.quarantine_a1(old["run_id"], old["revision"], 50)
    assert s["status"] == "awaiting_approval"
    assert s["order"]["a1_available"] == 150 and s["qualification"]["shortfall"] == 150
    assert s["history"][-1]["approval"]["valid"] is False
    assert s["approval"] is None and not s["drafts"]
    assert s["plans"][0]["summary"]["recovery_cost"] == 1200
    assert s["plans"][1]["summary"]["recovery_cost"] <= 400
    assert s["plans"][1]["plan"]["order_outcomes"][0]["completion_hour"] == 60
    assert s["scenario_hash"] != old["scenario_hash"]
    with pytest.raises(ValueError):
        e.approve(old["run_id"], old["revision"], old["plans"][1]["plan"]["plan_id"], "stale")
    with pytest.raises(ValueError):
        e.quarantine_a1(s["run_id"], s["revision"], 50)


@pytest.mark.parametrize("value", [0, -1, 201, True, 1.5, "50"])
def test_invalid_quarantine_never_changes_state(value):
    e = FinalsInvestigation()
    s = ready(e)
    with pytest.raises(ValueError):
        e.quarantine_a1(s["run_id"], s["revision"], value)
    assert e.runs[s["run_id"]] == s


def test_no_local_event_after_external_delivery():
    e = FinalsInvestigation()
    s = ready(e)
    e.runs[s["run_id"]]["execution"] = {"status": "monitoring"}
    with pytest.raises(ValueError, match="真实执行"):
        e.quarantine_a1(s["run_id"], s["revision"], 50)


@pytest.mark.parametrize("delay", [12, 24, 48, 72])
@pytest.mark.parametrize("quantity", [400, 600, 650, 1200])
def test_varied_inputs_conserve_material_and_budget(delay, quantity):
    e = FinalsInvestigation()
    s = ready(e, delay, quantity)
    assert s["status"] == "awaiting_approval"
    for row in s["plans"]:
        p = row["plan"]
        assert p["evidence"]["verified"]
        assert physical_allocation(s, p)["finished_quantity"] == quantity
        if p["profile"] == "balanced":
            assert row["summary"]["recovery_cost"] <= 400
        assert p["order_outcomes"][0]["completion_hour"] >= 4


def test_order_x_quantity_correction():
    assert rule_interpret("订单X改为650件，A1延期48小时", False).quantity == 650


def test_quarantine_api_rejects_forged_extra_fields():
    app = FinalsApplication()
    s = ready(app.offline)
    with pytest.raises(ValueError):
        app.post("/feedback/a1-quarantine", {"run_id":s["run_id"], "revision":s["revision"], "quantity":50, "approved":True})
    assert app.offline.runs[s["run_id"]]["order"]["a1_available"] == 200


def test_model_failure_during_event_cannot_restore_old_approval():
    e = FinalsInvestigation()
    s = ready(e)
    s = e.approve(s["run_id"], s["revision"], s["plans"][1]["plan"]["plan_id"], "test")
    class FailingModel:
        def complete_structured(self, **kwargs):
            raise TimeoutError("test failure")
    e.model = FailingModel()
    failed = e.quarantine_a1(s["run_id"], s["revision"], 50)
    assert failed["status"] == "model_or_validation_error"
    assert failed["approval"] is None and not failed["plans"] and not failed["drafts"]
    assert failed["history"][-1]["approval"]["valid"] is False
    assert e.runs[s["run_id"]]["order"]["a1_available"] == 150
