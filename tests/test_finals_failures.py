import json
import urllib.request
import urllib.error

import pytest

from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.finals_api import FinalsApplication, FinalsService
from delivery_guard.finals_failures import failure
from test_finals_execution import runtime


@pytest.mark.parametrize("text,case,code", [
    ("随便聊聊天", "ready", "INPUT_AMBIGUOUS"),
    ("A1硬度要95", "ready", "UNSUPPORTED_SCOPE"),
    ("A1延期20小时", "conflict", "EVIDENCE_CONFLICT"),
    ("A1延期20小时", "two_reply", "EVIDENCE_INSUFFICIENT"),
])
def test_clarification_category_not_model_failure(text, case, code):
    state = FinalsInvestigation().start(text, case_id=case)
    assert state["failure"]["error_code"] == code
    assert state["failure"]["external_records"] == {"erp": "none", "mes": "none"}
    assert not state["failure"]["retryable"]


def test_success_clears_current_failure():
    engine = FinalsInvestigation()
    s = engine.start("A1延期20小时", case_id="conflict")
    s = engine.reply(s["run_id"], s["revision"], "补充冲突解决资料，请核对", ["AP-RESOLVE"])
    assert s["status"] == "awaiting_approval" and s["failure"] is None


def test_response_loss_distinguishes_known_erp_unknown_mes(tmp_path):
    engine, state, service, erp, mes, _ = runtime(tmp_path)
    original = mes.execute
    def lost(command):
        original(command)
        raise TimeoutError("secret-provider-body-never-public")
    mes.execute = lost
    with pytest.raises(TimeoutError) as caught:
        service.execute(engine, state["run_id"], state["revision"], "tester", True)
    current = engine.runs[state["run_id"]]
    diag = failure("/integrations/execute", current, exc=caught.value)
    assert diag["error_code"] == "EXTERNAL_TIMEOUT_UNKNOWN"
    assert diag["external_records"] == {"erp": "known", "mes": "unknown"}
    assert not diag["retryable"] and "secret-provider" not in json.dumps(diag)
    assert erp.writes == mes.writes == 1


@pytest.mark.parametrize("status,code,records", [
    ("partial_failure", "EXTERNAL_PARTIAL", {"erp": "known", "mes": "none"}),
    ("erp_outcome_unknown", "EXTERNAL_TIMEOUT_UNKNOWN", {"erp": "unknown", "mes": "none"}),
])
def test_distinct_transport_stages(status, code, records):
    execution = {"status": status, "erp_command": {"command_id": "test"}}
    if status == "partial_failure": execution["erp_document"] = {"name": "TEST"}
    diag = failure("execute", {"execution": execution}, exc=TimeoutError())
    assert diag["error_code"] == code and diag["external_records"] == records


def test_readback_mismatch_does_not_say_no_record():
    state = {"execution": {"status": "erp_outcome_unknown", "erp_command": {"id": "test"}}}
    diag = failure("execute", state, exc=ValueError("ERP_READBACK_MATERIAL_MISMATCH"))
    assert diag["error_code"] == "READBACK_MISMATCH"
    assert diag["external_records"]["erp"] == "unknown"


def test_unknown_task_never_proves_no_external_writes():
    diag = failure("execute", None, uncertain_without_state=True)
    assert diag["external_records"] == {"erp": "unknown", "mes": "unknown"}


def test_http_stale_revision_is_structured_and_does_not_repeat_side_effects():
    app = FinalsApplication()
    s = app.post("/start", {"text": "A1延期24小时", "case_id": "ready"})
    service = FinalsService(0, app).start()
    try:
        payload = {"run_id": s["run_id"], "revision": s["revision"] + 10,
                   "actor": "test", "plan_id": s["plans"][0]["plan"]["plan_id"]}
        request = urllib.request.Request(f"http://127.0.0.1:{service.server.server_port}/approve",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as caught: urllib.request.urlopen(request)
        body = json.load(caught.value)
        assert body["failure"]["error_code"] == "STALE_APPROVAL"
        assert body["failure"]["revision"] == s["revision"]
        assert app.offline.runs[s["run_id"]]["approval"] is None
    finally:
        service.close()


def test_untrusted_error_text_not_echoed():
    body = FinalsApplication().failure_response("/start", {}, ValueError("api_key=DO_NOT_ECHO"))
    assert "DO_NOT_ECHO" not in json.dumps(body)


def test_failed_request_survives_restart_without_advancing_business_revision(tmp_path):
    from delivery_guard.integration.finals_state import FinalsStateStore
    store = FinalsStateStore(tmp_path)
    app = FinalsApplication(store=store)
    s = app.post("/start", {"text": "A1延期24小时", "case_id": "ready"})
    with pytest.raises(ValueError):
        app.post("/approve", {"run_id": s["run_id"], "revision": s["revision"] + 1,
                              "plan_id": s["plans"][0]["plan"]["plan_id"], "actor": "test"})
    restarted = FinalsApplication(store=store)
    restored = restarted.post("/resume", {"run_id": s["run_id"], "revision": s["revision"]})
    assert restored["failure"]["error_code"] == "STALE_APPROVAL"
    assert restored["failure_history"][-1] == restored["failure"]
    assert restored["revision"] == s["revision"] and restored["approval"] is None
    approved = restarted.post("/approve", {"run_id": s["run_id"], "revision": s["revision"],
                              "plan_id": s["plans"][0]["plan"]["plan_id"], "actor": "test"})
    assert approved["failure"] is None and len(approved["failure_history"]) == 1
    immediate = restarted.post("/resume", {"run_id": s["run_id"], "revision": approved["revision"]})
    assert immediate["failure"] is None and len(immediate["failure_history"]) == 1
    assert store.journal_evidence(s["run_id"])["chain_valid"]


def test_historical_runtime_error_does_not_mutate_old_journal(tmp_path):
    from delivery_guard.integration.finals_state import FinalsStateStore
    store = FinalsStateStore(tmp_path)
    s = FinalsInvestigation().start("A1延期24小时", case_id="ready")
    s["runtime_provenance"]["runtime_hash"] = "old-runtime"
    store.save(s)
    before = store.journal_evidence(s["run_id"])
    app = FinalsApplication(store=store)
    with pytest.raises(ValueError, match="READ_ONLY"):
        app.post("/approve", {"run_id": s["run_id"], "revision": s["revision"],
                             "plan_id": s["plans"][0]["plan"]["plan_id"], "actor": "test"})
    assert before == store.journal_evidence(s["run_id"])


def test_model_transport_failure_not_schema_failure_or_offline_success():
    class TimeoutModel:
        mode, model_name = "test_double", "timeout"
        def complete_structured(self, **kwargs): raise TimeoutError("private-response")
    s = FinalsInvestigation(model=TimeoutModel()).start("A1延期24小时", case_id="ready")
    assert s["status"] == "model_or_validation_error" and not s["plans"]
    assert s["failure"]["error_code"] == "MODEL_UNAVAILABLE"
    assert s["failure_history"][-1] == s["failure"]
    assert "private-response" not in json.dumps(s)


def test_malformed_provider_code_cannot_break_safe_diagnostics():
    error = RuntimeError("private")
    error.code = {"untrusted": "private"}
    assert failure("request", exc=error)["error_code"] == "SERVICE_UNAVAILABLE"


def test_dependency_change_does_not_offer_quantity_confirmation_bypass():
    from delivery_guard.finals_failures import state_failure
    d = state_failure({"status": "needs_reconciliation", "pending_execution_event": {"invalid_dependency": "ERP_CHANGED"}})
    assert d["error_code"] == "EXTERNAL_DEPENDENCY_CHANGED"


@pytest.mark.parametrize("code", ["WIKI_DUPLICATE_SOURCE", "WIKI_DUPLICATE_SPAN", "WIKI_SOURCE_HASH_MISMATCH", "SPAN_NOT_FOUND"])
def test_wiki_codes_are_preserved_without_document_text_leak(code):
    from delivery_guard.finals_wiki import WikiContractError
    diag = failure("/wiki", exc=WikiContractError(code, "private-document-name"))
    assert diag["error_code"] == code
    assert "private-document-name" not in json.dumps(diag)


def test_persisted_external_value_error_never_contains_provider_body(tmp_path):
    engine, state, service, _, mes, store = runtime(tmp_path)
    def invalid(command): raise ValueError("api_key=PRIVATE_PROVIDER_BODY")
    mes.execute = invalid
    with pytest.raises(ValueError):
        service.execute(engine, state["run_id"], state["revision"], "tester", True)
    restored = store.load(state["run_id"])
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(restored)
    assert restored["failure"]["error_code"] == "EXTERNAL_TIMEOUT_UNKNOWN"
