import json
import threading
import pytest
from urllib.request import Request, urlopen

from delivery_guard.demo_api import CASE, DemoApiApplication, DemoApiService
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.llm import ReplayLanguageModel


class InteractiveReplayModel(ReplayLanguageModel):
    def complete_structured(self, *, replay_key, system_prompt, user_text, schema):
        return super().complete_structured(
            replay_key="mendeley_seat_delay_email",
            system_prompt=system_prompt,
            user_text=user_text,
            schema=schema,
        )


def replay_graph_factory() -> DeliveryGuardGraph:
    return DeliveryGuardGraph(
        scenario_path=CASE / "scenario.json",
        knowledge_paths=[
            CASE / "customer_sla.md",
            CASE / "procurement_policy.md",
            CASE / "safety_policy.md",
        ],
        model=InteractiveReplayModel(
            CASE.parents[1] / "model_replays/mendeley_drill.json"
        ),
    )


@pytest.mark.parametrize("flag", ["erpnext_approval_invalidated", "openmes_approval_invalidated"])
@pytest.mark.parametrize("method", ["approve", "run_erpnext_integration", "run_openmes_integration", "run_integration"])
def test_stale_external_approval_blocks_all_dispatch_before_runtime(monkeypatch, flag, method):
    application = DemoApiApplication(graph_factory=replay_graph_factory)
    application.sessions["stale"] = {
        "result": {"status": "completed"},
        "graph": None,
        "erpnext_links": [{"erpnext_work_order": "MFG-TEST"}],
        flag: True,
    }

    def forbidden_runtime(*args, **kwargs):
        pytest.fail("stale approval crossed dispatch gate")

    monkeypatch.setattr(application, "_erpnext_runtime", forbidden_runtime)
    monkeypatch.setattr(application, "_openmes_runtime", forbidden_runtime)
    monkeypatch.setattr("delivery_guard.demo_api.run_partial_failure_demo", forbidden_runtime)
    with pytest.raises(ValueError, match="旧审批已失效"):
        getattr(application, method)({"session_id": "stale"})
    assert application.sessions["stale"][flag] is True


def request_json(base_url: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_health_keeps_model_and_erpnext_configuration_independent(monkeypatch):
    monkeypatch.setattr("delivery_guard.demo_api.load_runtime_credentials", lambda: None)
    monkeypatch.setenv("DELIVERY_GUARD_LLM_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("DELIVERY_GUARD_LLM_MODEL", "test-model")
    monkeypatch.setenv("DELIVERY_GUARD_API_KEY", "model-secret")
    for key in (
        "DELIVERY_GUARD_ERPNEXT_BASE_URL",
        "DELIVERY_GUARD_ERPNEXT_API_KEY",
        "DELIVERY_GUARD_ERPNEXT_API_SECRET",
        "DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    health = DemoApiApplication(graph_factory=replay_graph_factory).health()
    assert health["live_model_configured"] is True
    assert health["model_name"] == "test-model"
    assert health["erpnext_configured"] is False
    assert "model-secret" not in json.dumps(health)


def test_erpnext_revision_change_keeps_old_approval_invalid_on_later_polls(monkeypatch):
    before = {
        "source_revision": "erpnext:before",
        "content_hash": "before",
        "entities": {"Work Order": [], "Job Card": [], "Material Request": []},
    }
    after = {
        "source_revision": "erpnext:after",
        "content_hash": "after",
        "entities": {
            "Work Order": [{"name": "MFG-WO-1", "status": "In Process"}],
            "Job Card": [{"name": "JOB-1", "status": "Open"}],
            "Material Request": [],
        },
    }

    class SnapshotAdapter:
        def execution_snapshot(self, _watch_scope=None):
            return after

    application = DemoApiApplication(graph_factory=replay_graph_factory)
    application.sessions["session_feedback"] = {
        "result": {
            "workflow": {"approval": {"approval_id": "approval_old"}},
            "work_orders": [{"work_order_id": "old_draft"}],
        },
        "erpnext_baseline": before,
        "erpnext_watch_scope": {"Work Order": ["MFG-WO-1"], "Material Request": []},
        "erpnext_approval_invalidated": False,
    }
    monkeypatch.setattr(
        application,
        "_erpnext_runtime",
        lambda: (None, SnapshotAdapter(), None),
    )
    first = application.check_erpnext_feedback({"session_id": "session_feedback"})
    second = application.check_erpnext_feedback({"session_id": "session_feedback"})
    assert first["delta"]["changed"] is True
    assert second["delta"]["changed"] is False
    assert first["reconciliation"]["previous_approval_valid"] is False
    assert second["reconciliation"]["previous_approval_valid"] is False
    assert second["reconciliation"]["new_commands_blocked"] is True
    assert second["reconciliation"]["work_orders"] == []


def test_judge_api_runs_graph_approval_and_real_http_contract_sandbox():
    application = DemoApiApplication(graph_factory=replay_graph_factory)
    service = DemoApiService(application=application, port=0)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        status, contracts = request_json(service.base_url, "GET", "/api/v1/contracts")
        assert status == 200
        assert any(row["path"] == "/sandbox/v1/commands" for row in contracts["routes"])
        assert len(contracts["vendor_official_evidence"]) == 4
        assert all(
            item["links"] and all(link["url"].startswith("https://") for link in item["links"])
            for item in contracts["vendor_official_evidence"]
        )

        status, run = request_json(
            service.base_url,
            "POST",
            "/api/v1/agent/run",
            {
                "text": (
                    "The public Mendeley seat supplier cannot dispatch for the next "
                    "48 hours. Please assess affected orders."
                )
            },
        )
        assert status == 200
        assert run["run_mode"] == "replay"
        assert run["result"]["status"] == "awaiting_approval"
        assert run["result"]["impact"]["affected_orders"]

        status, approved = request_json(
            service.base_url,
            "POST",
            "/api/v1/agent/approve",
            {"session_id": run["session_id"], "profile": "balanced"},
        )
        assert status == 200
        assert approved["result"]["status"] == "completed"
        assert approved["result"]["work_orders"]

        status, integrated = request_json(
            service.base_url,
            "POST",
            "/api/v1/integration/run",
            {
                "session_id": run["session_id"],
                "profile": "kingdee_blacklake_contract_profile",
            },
        )
        assert status == 200
        report = integrated["report"]
        assert report["http_boundary"]["command_posts"] == 2
        assert report["http_boundary"]["callback_posts"] == 2
        assert report["overall_business_status"] == "PARTIALLY_APPLIED"
        assert {item["business_status"] for item in report["transport_acks"]} == {"PENDING"}
        assert {item["business_status"] for item in report["callbacks"]} == {"APPLIED", "REJECTED"}
        assert report["replan"]["status"] == "awaiting_approval"
        assert report["old_approval_reused"] is False
    finally:
        service.close()
        thread.join(timeout=2)
