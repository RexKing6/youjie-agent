from copy import deepcopy
import json
import urllib.error
import urllib.request

import pytest

from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.finals_api import FinalsApplication, FinalsService
from delivery_guard.finals_provenance import export_evidence
from delivery_guard.integration.finals_state import FinalsStateStore


def test_new_run_source_model_and_registry_provenance():
    engine=FinalsInvestigation()
    state=engine.start("A1延期24小时",case_id="ready")
    provenance=state["runtime_provenance"]
    assert provenance["source_sha256"]["finals_agent.py"]
    assert provenance["registry_sha256"]
    assert provenance["model_name"]=="none"
    assert export_evidence(state,engine.runtime_provenance)["runtime_compatible"]


@pytest.mark.parametrize("legacy",[False,True])
def test_restore_changed_or_unknown_runtime_is_read_only(tmp_path,legacy):
    store=FinalsStateStore(tmp_path)
    engine=FinalsInvestigation()
    state=engine.start("A1延期24小时",case_id="ready")
    if legacy: state.pop("runtime_provenance")
    else: state["runtime_provenance"]["runtime_hash"]="different-code-or-model"
    store.save(state)
    app=FinalsApplication(store=store)
    resumed=app.post("/resume",{"run_id":state["run_id"],"revision":state["revision"]})
    assert resumed["runtime_compatible"] is False
    with pytest.raises(ValueError,match="READ_ONLY"):
        app.post("/approve",{"run_id":state["run_id"],"revision":state["revision"],
                             "plan_id":state["plans"][0]["plan"]["plan_id"],"actor":"test"})
    assert not app.evidence(state["run_id"])["runtime_compatible"]
    assert app.evidence(state["run_id"])["state"]["approval"] is None


def test_journal_retains_old_snapshot_and_recovers_append_before_replace(tmp_path,monkeypatch):
    store=FinalsStateStore(tmp_path)
    state=FinalsInvestigation().start("A1延期24小时",case_id="ready")
    store.save(state)
    store.save(state)
    assert store.journal_evidence(state["run_id"])["entries"]==1
    changed=deepcopy(state)
    changed["revision"]+=1
    changed["question"]="new durable revision"
    import delivery_guard.integration.finals_state as module
    def interrupted(*args): raise OSError("simulated crash before replace")
    monkeypatch.setattr(module.os,"replace",interrupted)
    with pytest.raises(OSError): store.save(changed)
    restored=FinalsStateStore(tmp_path)
    assert restored.load(state["run_id"])["question"]=="new durable revision"
    assert restored.journal_evidence(state["run_id"])["entries"]==2
    assert json.loads(restored.path(state["run_id"]).read_text())["state"]["revision"]==state["revision"]


def test_journal_corruption_blocks_export(tmp_path):
    store=FinalsStateStore(tmp_path)
    state=FinalsInvestigation().start("A1延期24小时",case_id="ready")
    store.save(state)
    journal=store.path(state["run_id"]).with_suffix(".journal.jsonl")
    journal.write_text(journal.read_text().replace('"sequence": 1','"sequence": 8',1))
    with pytest.raises(ValueError,match="JOURNAL_INTEGRITY"):
        FinalsApplication(store=store).evidence(state["run_id"])


def test_secret_shaped_fields_never_export():
    engine=FinalsInvestigation()
    state=engine.start("A1延期24小时",case_id="ready")
    state["nested"]={"api_key":"test-placeholder-not-a-real-key"}
    with pytest.raises(ValueError,match="EXPORT_BLOCKED"):
        export_evidence(state,engine.runtime_provenance)


def test_http_evidence_requires_local_session_and_exact_run(tmp_path):
    app=FinalsApplication(store=FinalsStateStore(tmp_path))
    state=app.post("/start",{"text":"A1延期24小时","case_id":"ready"})
    service=FinalsService(0,app).start()
    base=f"http://127.0.0.1:{service.server.server_port}"
    path=base+f"/runs/{state['run_id']}/evidence"
    try:
        with pytest.raises(urllib.error.HTTPError) as error: urllib.request.urlopen(path)
        assert error.value.code==403
        request=urllib.request.Request(path,headers={"X-Youjie-Session":app.session_capability})
        payload=json.load(urllib.request.urlopen(request))
        assert payload["runtime_compatible"] and payload["state"]["run_id"]==state["run_id"]
        assert payload["journal"]["entries"]==1
        assert "session_capability" not in json.dumps(payload)
        request=urllib.request.Request(path,headers={"X-Youjie-Session":app.session_capability,"Origin":"https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
        assert error.value.code==403
    finally: service.close()
