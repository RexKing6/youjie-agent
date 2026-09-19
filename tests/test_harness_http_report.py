"""Validation-helper regression only: no live model or HTTP evidence."""
import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest


def module():
    spec=importlib.util.spec_from_file_location("harness_http_probe",Path(__file__).parents[1]/"scripts/validate_harness_http.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quota_failure_saved_without_body(tmp_path):
    def request(path,payload=None):
        if path=="/progress": return None
        return {"status":"model_or_validation_error","failure":{"error_code":"MODEL_QUOTA_EXHAUSTED","body":"secret-marker"}}
    target=tmp_path/"quota.json"
    result=module().save_probe(target,request)
    assert not result["passed"] and result["stage"]=="start"
    assert result["failure_code"]=="MODEL_QUOTA_EXHAUSTED"
    assert "secret-marker" not in target.read_text()
    assert json.loads(target.read_text())==result


def test_network_failure_saved_and_existing_file_preserved(tmp_path):
    calls=[]
    def request(*args):
        calls.append(args)
        raise RuntimeError("secret-marker")
    target=tmp_path/"failure.json"
    mod=module()
    result=mod.save_probe(target,request)
    assert not result["passed"] and result["error_type"]=="RuntimeError"
    before=target.read_bytes(); count=len(calls)
    with pytest.raises(FileExistsError): mod.save_probe(target,request)
    assert target.read_bytes()==before and len(calls)==count
    assert b"secret-marker" not in before


@pytest.mark.parametrize("export_fails",[False,True])
def test_budget_and_export_outcomes_saved(tmp_path,export_fails):
    polled=threading.Event()
    paths=[]
    def request(path,payload=None):
        paths.append(path)
        if path=="/progress":
            polled.set()
            return {"updated_at":time.time(),"events":[{"message":"test-only"}]}
        if path=="/start":
            assert polled.wait(2)
            return {"status":"awaiting_approval","run_id":"test-only","revision":1}
        if path=="/constraints/budget":
            cost,late=(0,48) if payload["budget"]==200 else (300,16)
            return {"revision":payload["revision"]+1,"approval":None,"drafts":[],"plans":[{},
                {"summary":{"recovery_cost":cost},"plan":{"order_outcomes":[{"late_hours":late}]}}]}
        if export_fails: raise TimeoutError("secret-marker")
        return {"test_double":True}
    result=module().save_probe(tmp_path/"test.json",request)
    assert result["passed"] is not export_fails
    assert result["stage"]==("export" if export_fails else "complete")
    assert result["progress_seen"]
    assert paths.count("/constraints/budget")==2
    assert result["external_writes"]==0
